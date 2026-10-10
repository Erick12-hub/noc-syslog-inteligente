"""
Propuestas de acción con aprobación humana (RF-13): el flujo seguro obligatorio.

    evento -> validación -> PROPUESTA -> REVISIÓN HUMANA -> APROBACIÓN
           -> EJECUCIÓN AUTORIZADA -> VERIFICACIÓN -> AUDITORÍA

    POST /api/incidents/<id>/suggest          El asistente propone acciones
    GET  /api/incidents/<id>/proposals        Propuestas del incidente
    POST /api/proposals/<id>/review           {decision: aprobar|rechazar, comment}
    POST /api/proposals/<id>/execute          Ejecución (SIMULADA) - solo si está aprobada
    POST /api/proposals/<id>/verify           {result} - el humano verifica el resultado

EL "ASISTENTE DE IA" DEL MVP es un motor de reglas (no un modelo de lenguaje):
mira datos ESTRUCTURADOS del incidente (código del evento, reglas cumplidas) y
elige acciones de un CATÁLOGO cerrado. Así se demuestra la política que debe
cumplir cualquier agente de IA, incluido uno real en el Corte 3:
  - Solo PROPONE; nunca aprueba ni ejecuta (actor 'asistente_ia').
  - Los comandos salen del catálogo, no del texto del log. Los parámetros que
    se toman del log (una IP, una interfaz) se VALIDAN con reglas estrictas.
  - Si el incidente viene de un log con posible prompt injection, NO propone
    comandos sobre equipos: solo escalar a seguridad.
  - Quien aprueba debe ser un humano distinto del que propone (separación de
    funciones) y la aprobación exige un comentario.
"""
import ipaddress
import re

from flask import Blueprint, current_app, jsonify, request

from .db import audit, get_db, now_iso

bp = Blueprint("proposals", __name__, url_prefix="/api")

AI_ACTOR = "asistente_ia"
RE_IFACE = re.compile(r"\b((?:GigabitEthernet|TenGigabitEthernet|FastEthernet|Serial|Gi|Te)\d+(?:/\d+){1,3})\b")
RE_IPV4 = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")

# Catálogo cerrado de acciones. {iface} e {ip} se llenan con valores VALIDADOS.
CATALOG = {
    "diagnostico_interfaz": {
        "Cisco": "show interfaces {iface}", "Huawei": "display interface {iface}",
        "risk": "bajo", "why": "Diagnóstico de solo lectura de la interfaz afectada."},
    "bloquear_ip": {
        "Fortinet": "config firewall address / edit \"BLOQ-{ip}\" / set subnet {ip}/32 + política deny",
        "Cisco": "ip access-list extended NOC-BLOQUEO / deny ip host {ip} any",
        "Huawei": "acl 3999 / rule deny ip source {ip} 0",
        "risk": "medio", "why": "Bloquear temporalmente la IP de origen de los intentos fallidos."},
    "restaurar_logs": {
        "Huawei": "info-center enable", "Cisco": "logging host <servidor-noc>",
        "Fortinet": "config log syslogd setting / set status enable",
        "risk": "alto", "why": "Volver a activar el envío de logs que alguien apagó."},
    "deshabilitar_cuenta": {
        "Cisco": "no username {user}", "Huawei": "aaa / local-user {user} state block",
        "Fortinet": "config system admin / edit {user} / set status disable (según versión)",
        "risk": "alto", "why": "Suspender la cuenta de servicio que hizo cambios no autorizados."},
    "revisar_cambios": {
        "Cisco": "show archive log config all", "Huawei": "display configuration commit changes",
        "Fortinet": "execute log filter category event + execute log display",
        "risk": "bajo", "why": "Revisar qué cambió en la configuración y quién lo hizo."},
    "escalar_seguridad": {
        "any": "(sin comando) Escalar al equipo de seguridad",
        "risk": "bajo", "why": "Revisión humana del origen del mensaje; no se actúa sobre equipos."},
}
RE_USER = re.compile(r"^[A-Za-z][\w.\-]{1,31}$")


def _valid_ip(text):
    for cand in RE_IPV4.findall(text or ""):
        try:
            ip = ipaddress.ip_address(cand)
            if not ip.is_loopback:
                return str(ip)
        except ValueError:
            continue
    return None


def suggest_for(conn, inc) -> list[dict]:
    """Elige acciones del catálogo según datos estructurados del incidente."""
    ev = conn.execute("SELECT message, mnemonic, flags, vendor FROM syslog_events WHERE id = ?",
                      (inc["event_id"],)).fetchone() if inc["event_id"] else None
    flags = set((ev["flags"] or "").split(",")) if ev else set()
    vendor = (inc["device_vendor"] if inc["device_vendor"] != "Otro" else None) or (ev["vendor"] if ev else "Cisco")
    key = inc["correlation_key"] or ""
    msg, mnemonic = (ev["message"], ev["mnemonic"] or "") if ev else ("", "")

    def item(action, **params):
        tpl = CATALOG[action].get(vendor) or CATALOG[action].get("any") or CATALOG[action].get("Cisco")
        return {"action": action, "command": tpl.format(**params), "risk": CATALOG[action]["risk"],
                "justification": CATALOG[action]["why"]}

    # 1. Log con posible prompt injection: NO se proponen comandos sobre equipos
    if "posible_prompt_injection" in flags:
        return [item("escalar_seguridad")]
    out = []
    if "logs_deshabilitados" in key or "logs_deshabilitados" in flags:
        out.append(item("restaurar_logs"))
    if "cuenta_servicio" in key or "cuenta_servicio" in flags:
        m = re.search(r'(?:\bby\s+|User=)"?([\w.\-]+)', msg)
        if m and RE_USER.match(m.group(1)):          # usuario validado
            out.append(item("deshabilitar_cuenta", user=m.group(1)))
    if "cambio_fuera_de_horario" in key or "cambio_config" in flags:
        out.append(item("revisar_cambios"))
    if "fuerza_bruta" in key or "login_fallido" in flags:
        ip = _valid_ip(msg)                            # IP validada con ipaddress
        if ip:
            out.append(item("bloquear_ip", ip=ip))
    if "UPDOWN" in mnemonic or "LINK_STATE" in mnemonic:
        m = RE_IFACE.search(msg)
        if m and vendor in ("Cisco", "Huawei"):
            out.append(item("diagnostico_interfaz", iface=m.group(1)))
    return out or [item("escalar_seguridad")]


def _operator():
    return current_app.config["DEFAULT_OPERATOR"]


def _incident(conn, incident_id):
    return conn.execute(
        "SELECT i.*, d.vendor AS device_vendor FROM incidents i LEFT JOIN devices d ON d.id = i.device_id "
        "WHERE i.id = ?", (incident_id,)).fetchone()


@bp.post("/incidents/<int:incident_id>/suggest")
def suggest(incident_id):
    conn = get_db()
    inc = _incident(conn, incident_id)
    if inc is None:
        return jsonify(error="Incidente no encontrado"), 404
    if inc["status"] == "cerrado":
        return jsonify(errors=["El incidente está cerrado"]), 409
    created = []
    for s in suggest_for(conn, inc):
        dup = conn.execute("SELECT 1 FROM action_proposals WHERE incident_id = ? AND command = ? "
                           "AND status IN ('pendiente','aprobada')", (incident_id, s["command"])).fetchone()
        if dup:
            continue
        cur = conn.execute(
            "INSERT INTO action_proposals (incident_id, proposed_by, command, justification, risk, "
            "status, created_at) VALUES (?, ?, ?, ?, ?, 'pendiente', ?)",
            (incident_id, AI_ACTOR, s["command"], s["justification"], s["risk"], now_iso()))
        created.append(cur.lastrowid)
        audit(conn, AI_ACTOR, "proposal.create", "action_proposals", cur.lastrowid,
              f"incidente={incident_id} riesgo={s['risk']} accion={s['action']}")
    conn.commit()
    return jsonify(created=created, proposals=_list(conn, incident_id)), 201


def _list(conn, incident_id):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM action_proposals WHERE incident_id = ? ORDER BY id", (incident_id,))]


@bp.get("/incidents/<int:incident_id>/proposals")
def list_proposals(incident_id):
    return jsonify(_list(get_db(), incident_id))


def _load(conn, pid, expected_status):
    p = conn.execute("SELECT * FROM action_proposals WHERE id = ?", (pid,)).fetchone()
    if p is None:
        return None, (jsonify(error="Propuesta no encontrada"), 404)
    if p["status"] != expected_status:
        return None, (jsonify(errors=[f"La propuesta está '{p['status']}'; se requiere '{expected_status}'"]), 409)
    return p, None


@bp.post("/proposals/<int:pid>/review")
def review(pid):
    """Paso de REVISIÓN HUMANA: aprobar o rechazar, con comentario obligatorio."""
    conn = get_db()
    p, err = _load(conn, pid, "pendiente")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    reviewer = _operator()
    if data.get("actor") == AI_ACTOR or reviewer == AI_ACTOR:
        audit(conn, AI_ACTOR, "proposal.review", "action_proposals", pid, "intento de autoaprobación", "bloqueado")
        return jsonify(errors=["Un agente de IA no puede aprobar propuestas"]), 403
    if reviewer == p["proposed_by"]:
        return jsonify(errors=["Quien propone no puede aprobar su propia propuesta"]), 403
    decision = data.get("decision")
    comment = (data.get("comment") or "").strip()
    if decision not in ("aprobar", "rechazar"):
        return jsonify(errors=["Decisión inválida: aprobar o rechazar"]), 400
    if len(comment) < 5:
        return jsonify(errors=["Escriba el motivo de la decisión (mínimo 5 caracteres)"]), 400
    status = "aprobada" if decision == "aprobar" else "rechazada"
    conn.execute("UPDATE action_proposals SET status = ?, reviewed_by = ?, reviewed_at = ?, result = ? "
                 "WHERE id = ?", (status, reviewer, now_iso(), f"Revisión: {comment}", pid))
    conn.commit()
    audit(conn, reviewer, f"proposal.{status}", "action_proposals", pid, comment)
    return jsonify(dict(conn.execute("SELECT * FROM action_proposals WHERE id = ?", (pid,)).fetchone()))


@bp.post("/proposals/<int:pid>/execute")
def execute(pid):
    """EJECUCIÓN AUTORIZADA (simulada): solo propuestas aprobadas por un humano."""
    conn = get_db()
    p, err = _load(conn, pid, "aprobada")
    if err:
        audit(conn, _operator(), "proposal.execute", "action_proposals", pid, "sin aprobación", "bloqueado")
        return err
    result = (f"{p['result']} | EJECUCIÓN SIMULADA {now_iso()}: '{p['command']}' "
              f"(en el MVP no se envían comandos a equipos reales)")
    conn.execute("UPDATE action_proposals SET status = 'ejecutada', result = ? WHERE id = ?", (result, pid))
    conn.commit()
    audit(conn, _operator(), "proposal.execute", "action_proposals", pid, p["command"])
    return jsonify(dict(conn.execute("SELECT * FROM action_proposals WHERE id = ?", (pid,)).fetchone()))


@bp.post("/proposals/<int:pid>/verify")
def verify(pid):
    """VERIFICACIÓN: el humano confirma el resultado de la acción ejecutada."""
    conn = get_db()
    p, err = _load(conn, pid, "ejecutada")
    if err:
        return err
    note = ((request.get_json(silent=True) or {}).get("result") or "").strip()
    if len(note) < 5:
        return jsonify(errors=["Describa el resultado verificado (mínimo 5 caracteres)"]), 400
    conn.execute("UPDATE action_proposals SET status = 'verificada', result = ? WHERE id = ?",
                 (f"{p['result']} | Verificación: {note}", pid))
    conn.commit()
    audit(conn, _operator(), "proposal.verify", "action_proposals", pid, note)
    return jsonify(dict(conn.execute("SELECT * FROM action_proposals WHERE id = ?", (pid,)).fetchone()))
