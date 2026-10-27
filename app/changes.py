"""
Fase 10.2: SOLICITUDES DE CAMBIO con matriz de riesgo, rollback y ventana.

    GET  /api/changes?estado=activos|cerrados|todos   Lista
    POST /api/changes                                 Crear (queda en BORRADOR)
    GET  /api/changes/<id>                            Detalle
    PUT  /api/changes/<id>                            Editar (solo borrador, solo quien la creó)
    POST /api/changes/<id>/submit                     Enviar a aprobación (-> PENDIENTE)
    POST /api/changes/<id>/cancel                     Cancelar {reason}
    POST /api/changes/assess                          Evaluar riesgo sin guardar (ayuda del formulario)

POR QUÉ
    Ningún cambio en un equipo se hace "a mano y sin avisar". Cada cambio dice
    QUÉ comandos se aplican, POR QUÉ, CÓMO se deshace (rollback, obligatorio),
    CÓMO se verifica y CUÁNDO (ventana). Su riesgo se calcula con una matriz
    IMPACTO x PROBABILIDAD, y el riesgo decide cuántas aprobaciones necesita
    (Fase 10.3: aprobación, ejecución, verificación y rollback).

MATRIZ DE RIESGO (3 x 3)          Probabilidad de que algo salga mal
                                  1 improbable   2 posible   3 probable
        Impacto 3 alto                 3 medio      6 alto      9 alto
        Impacto 2 medio                2 bajo       4 medio     6 alto
        Impacto 1 bajo                 1 bajo       2 bajo      3 medio

    bajo  -> 1 aprobación, ventana opcional
    medio -> 1 aprobación, ventana obligatoria
    alto  -> 2 aprobaciones de personas distintas, ventana obligatoria

IMPACTO MÍNIMO: el solicitante elige el impacto, pero los comandos imponen un
mínimo (no se puede llamar "bajo" a un 'shutdown' o a un cambio de IP). Así el
riesgo no depende solo de la opinión de quien pide el cambio.

COMANDOS PROHIBIDOS en un cambio (ni con aprobación): credenciales, guardar,
borrar, reiniciar, copiar archivos y apagar el envío de logs al NOC. El
'configure terminal' y el 'end' los agrega el NOC al ejecutar.
"""
import json
import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from .auth import actor, current_user
from .config import Config
from .console import RE_META, check as check_readonly
from .db import audit, get_db, now_iso
from .interfaces import normalize_for_vendor
from .timeutil import local_tz, to_iso_utc

bp = Blueprint("changes", __name__, url_prefix="/api/changes")

LEVELS = {1: "bajo", 2: "medio", 3: "alto"}
PROBABILITY = {1: "improbable", 2: "posible", 3: "probable"}
APPROVALS = {"bajo": 1, "medio": 1, "alto": 2}
STATUSES = ("borrador", "pendiente", "aprobado", "rechazado", "en_ejecucion", "ejecutado",
            "fallido", "revertido", "cancelado")
ACTIVE = ("borrador", "pendiente", "aprobado", "en_ejecucion")
MAX_LINES = 30
MAX_LINE = 120
MAX_WINDOW_HOURS = 4
PAST_TOLERANCE = timedelta(minutes=5)
RE_WINDOW = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")      # <input type="datetime-local">

# Comandos que NUNCA van en un cambio (motivo)
FORBIDDEN = [
    (r"^(conf(igure)?|end)\b", "no escriba 'configure terminal' ni 'end': el NOC los agrega al ejecutar"),
    (r"^do\b", "'do' ejecuta comandos de modo privilegiado desde la configuración"),
    (r"^(write|copy|erase|delete|format|reload|boot|config-register|archive config)\b",
     "guarda, borra, copia o reinicia el equipo (préstamo: nunca se guarda)"),
    (r"^(no\s+)?(username|enable\s+(secret|password)|password|secret|crypto\s+(key|pki)|"
     r"snmp-server\s+community|aaa|key\s+chain)\b", "maneja credenciales: no se gestionan por cambios"),
    (r"^no\s+(logging|archive|service\s+timestamps|service\s+sequence-numbers)\b",
     "apaga o degrada el registro de eventos que recibe el NOC"),
    (r"^logging\s+(off|on\s+.*disable)\b", "apaga el registro de eventos"),
]
# Comandos que obligan un impacto mínimo (nivel, motivo)
MIN_IMPACT = [
    (r"^(no\s+)?shutdown\b", 3, "apaga o enciende una interfaz (puede cortar la conexión)"),
    (r"^(no\s+)?ip\s+address\b", 3, "cambia una dirección IP"),
    (r"^(no\s+)?ip\s+route\b|^(no\s+)?router\s", 3, "cambia el enrutamiento"),
    (r"^(no\s+)?(ip\s+access-group|access-list|ip\s+access-list)\b", 3, "cambia filtros de tráfico (ACL)"),
    (r"^(no\s+)?(switchport|spanning-tree|vlan)\b", 3, "cambia la conmutación (VLAN o puertos)"),
    (r"^(no\s+)?(ip\s+default-gateway|line\s+(vty|con))\b", 3, "cambia el acceso de gestión al equipo"),
    (r"^(no\s+)?(logging|ntp|clock)\b", 2, "cambia el registro de eventos o la hora (afecta al NOC)"),
    (r"^(no\s+)?hostname\b", 2, "cambia el nombre que aparece en los eventos"),
    (r"^(no\s+)?(service|ip\s+domain|ip\s+http|banner)\b", 2, "cambia un servicio del equipo"),
]


def risk_level(impact: int, probability: int) -> tuple[int, str]:
    score = impact * probability
    return score, ("bajo" if score <= 2 else "medio" if score <= 4 else "alto")


def _lines(text) -> list[str]:
    """Líneas del cuadro de texto: sin vacías ni comentarios '!', con la sangría de los submodos."""
    return [l.rstrip() for l in str(text or "").replace("\r", "").split("\n")
            if l.strip() and not l.strip().startswith("!")]


def check_commands(lines: list[str], label: str, required: bool = True) -> list[str]:
    errors = []
    if required and not lines:
        errors.append(f"{label}: escriba al menos un comando")
    if len(lines) > MAX_LINES:
        errors.append(f"{label}: máximo {MAX_LINES} líneas")
    for i, line in enumerate(lines, 1):
        cmd = re.sub(r"\s+", " ", line.strip()).lower()
        if len(line) > MAX_LINE:
            errors.append(f"{label}, línea {i}: más de {MAX_LINE} caracteres")
        elif RE_META.search(line):
            errors.append(f"{label}, línea {i}: caracteres no permitidos (; | & ` $ > <)")
        else:
            for pattern, why in FORBIDDEN:
                if re.match(pattern, cmd):
                    errors.append(f"{label}, línea {i} '{line.strip()[:50]}': prohibido, {why}")
                    break
    return errors


def minimum_impact(conn, device, lines: list[str]) -> tuple[int, list[str]]:
    """Impacto mínimo que imponen los comandos (1 bajo, 2 medio, 3 alto) y sus motivos."""
    level, reasons = 1, []
    mgmt = set()
    if device is not None:      # interfaz que tiene la IP de gestión del inventario
        mgmt = {r["name"].lower() for r in conn.execute(
            "SELECT name FROM interfaces WHERE device_id = ? AND ip_address = ?", (device["id"], device["ip"]))}
    for line in lines:
        cmd = re.sub(r"\s+", " ", line.strip()).lower()
        for pattern, lvl, why in MIN_IMPACT:
            if re.match(pattern, cmd):
                if lvl > level:
                    level = lvl
                text = f"'{line.strip()[:40]}': {why}"
                if text not in reasons:
                    reasons.append(text)
                break
        if cmd.startswith("interface ") and normalize_for_vendor("Cisco", line.strip()[10:].strip()).lower() in mgmt:
            level = 3
            reasons.append(f"'{line.strip()[:40]}': es la interfaz de GESTIÓN (por ella llega el NOC)")
    return level, reasons


def _parse_window(value: str):
    """'2026-10-23T19:00' (hora de Colombia) -> datetime UTC, o None si viene vacío."""
    value = (value or "").strip()
    if not value:
        return None
    if not RE_WINDOW.match(value):
        raise ValueError
    return datetime.strptime(value, "%Y-%m-%dT%H:%M").replace(tzinfo=local_tz()).astimezone(timezone.utc)


def validate(conn, data: dict, user: str, now: datetime | None = None) -> tuple[dict, list[str]]:
    """Valida todo el formulario y calcula el riesgo. Devuelve (valores, errores)."""
    now = now or datetime.now(timezone.utc)
    errors, v = [], {}
    device = None
    try:
        device = conn.execute("SELECT * FROM devices WHERE id = ?", (int(data.get("device_id")),)).fetchone()
    except (TypeError, ValueError):
        pass
    if device is None:
        errors.append("Elija el equipo")
    else:
        if device["vendor"] != "Cisco":
            errors.append("En esta versión los cambios se ejecutan solo en equipos Cisco")
        if device["connection_mode"] == "ninguno":
            errors.append("El equipo no tiene modo de conexión: el NOC no podría aplicar ni verificar el cambio")
        v["device_id"], v["device_name"] = device["id"], device["name"]

    v["title"] = str(data.get("title") or "").strip()
    if not 5 <= len(v["title"]) <= 120:
        errors.append("Título: entre 5 y 120 caracteres")
    v["reason"] = str(data.get("reason") or "").strip()
    if not 10 <= len(v["reason"]) <= 1000:
        errors.append("Justificación: entre 10 y 1000 caracteres (por qué se necesita el cambio)")

    commands, rollback, verify = _lines(data.get("commands")), _lines(data.get("rollback")), _lines(data.get("verify"))
    errors += check_commands(commands, "Comandos")
    errors += check_commands(rollback, "Rollback")
    if commands and rollback and [c.strip() for c in commands] == [r.strip() for r in rollback]:
        errors.append("Rollback: no puede ser igual a los comandos del cambio (debe deshacerlos)")
    if len(verify) > 5:
        errors.append("Verificación: máximo 5 comandos")
    for i, cmd in enumerate(verify, 1):
        ok, why = check_readonly(device["vendor"] if device else "Cisco", cmd.strip(), user)
        if not ok:
            errors.append(f"Verificación, línea {i} '{cmd.strip()[:40]}': {why}")
    v["commands"], v["rollback"], v["verify"] = "\n".join(commands), "\n".join(rollback), "\n".join(c.strip() for c in verify)

    try:
        v["impact"], v["probability"] = int(data.get("impact")), int(data.get("probability"))
        if v["impact"] not in LEVELS or v["probability"] not in PROBABILITY:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("Impacto y probabilidad: valores de 1 a 3")
        v["impact"], v["probability"] = 1, 1
    v["min_impact"], reasons = minimum_impact(conn, device, commands)
    v["risk_reasons"] = " | ".join(reasons) or None
    if v["impact"] < v["min_impact"]:
        errors.append(f"Impacto {LEVELS[v['impact']]} es menor que el mínimo que imponen los comandos "
                      f"({LEVELS[v['min_impact']]}): " + "; ".join(reasons))
    v["risk_score"], v["risk_level"] = risk_level(max(v["impact"], v["min_impact"]), v["probability"])
    v["approvals_required"] = APPROVALS[v["risk_level"]]

    try:
        start, end = _parse_window(data.get("window_start")), _parse_window(data.get("window_end"))
    except ValueError:
        start = end = None
        errors.append("Ventana: formato de fecha y hora inválido")
    else:
        if (start is None) != (end is None):
            errors.append("Ventana: indique inicio y fin")
        elif start is None and v["risk_level"] != "bajo":
            errors.append(f"Ventana: obligatoria para riesgo {v['risk_level']} (cuándo se puede ejecutar)")
        elif start is not None:
            if end <= start:
                errors.append("Ventana: el fin debe ser posterior al inicio")
            elif end - start > timedelta(hours=MAX_WINDOW_HOURS):
                errors.append(f"Ventana: máximo {MAX_WINDOW_HOURS} horas")
            if start < now - PAST_TOLERANCE:
                errors.append("Ventana: el inicio ya pasó")
    v["window_start"] = to_iso_utc(start) if start else None
    v["window_end"] = to_iso_utc(end) if end else None
    return v, errors


def assess_summary(v: dict) -> dict:
    return {"risk_score": v["risk_score"], "risk_level": v["risk_level"], "impact": v["impact"],
            "probability": v["probability"], "min_impact": v["min_impact"],
            "min_impact_name": LEVELS[v["min_impact"]], "approvals_required": v["approvals_required"],
            "window_required": v["risk_level"] != "bajo",
            "reasons": v["risk_reasons"].split(" | ") if v["risk_reasons"] else []}


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------
def get_change(conn, cid):
    return conn.execute("SELECT * FROM change_requests WHERE id = ?", (cid,)).fetchone()


def _public(row) -> dict:
    d = dict(row)
    d["risk_reasons"] = d["risk_reasons"].split(" | ") if d["risk_reasons"] else []
    return d


def _overlaps(conn, row) -> list[str]:
    """Otros cambios activos del mismo equipo cuya ventana se cruza con esta."""
    if not row["window_start"]:
        return []
    rows = conn.execute(
        "SELECT id, title FROM change_requests WHERE device_id = ? AND id != ? AND status IN "
        "('pendiente', 'aprobado', 'en_ejecucion') AND window_start IS NOT NULL "
        "AND window_start < ? AND window_end > ?",
        (row["device_id"], row["id"], row["window_end"], row["window_start"])).fetchall()
    return [f"La ventana se cruza con el cambio #{r['id']} ({r['title']}) del mismo equipo" for r in rows]


def _is_owner_or_admin(row, owner_only=False) -> bool:
    user = current_user()
    if user is None:
        return False
    if row["requested_by"] == user["username"]:
        return True
    return not owner_only and user["role"] == "admin_seguridad"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@bp.get("")
def list_changes():
    estado = request.args.get("estado", "activos")
    conn = get_db()
    if estado == "activos":
        rows = conn.execute(f"SELECT * FROM change_requests WHERE status IN ({','.join('?' * len(ACTIVE))}) "
                            "ORDER BY id DESC", ACTIVE).fetchall()
    elif estado == "cerrados":
        rows = conn.execute(f"SELECT * FROM change_requests WHERE status NOT IN ({','.join('?' * len(ACTIVE))}) "
                            "ORDER BY id DESC", ACTIVE).fetchall()
    elif estado == "todos":
        rows = conn.execute("SELECT * FROM change_requests ORDER BY id DESC").fetchall()
    else:
        return jsonify(errors=["Estado inválido. Opciones: activos, cerrados, todos"]), 400
    return jsonify([_public(r) for r in rows])


@bp.post("/assess")
def assess():
    """Calcula el riesgo mientras se llena el formulario (no guarda ni audita)."""
    v, errors = validate(get_db(), request.get_json(silent=True) or {}, actor())
    return jsonify(assessment=assess_summary(v), errors=errors)


AI_ACTOR = "asistente_ia"


@bp.post("")
def create_change():
    conn = get_db()
    user = actor()
    if user == AI_ACTOR:          # Fase 11.2: un agente de IA no pide cambios sobre equipos
        audit(conn, user, "change.bloqueado_ia", "change_requests", None, "intento de crear un cambio", "bloqueado")
        return jsonify(errors=["Un agente de IA no crea solicitudes de cambio: solo propone acciones del "
                               "catálogo en un incidente, para revisión humana"]), 403
    v, errors = validate(conn, request.get_json(silent=True) or {}, user)
    if errors:
        return jsonify(errors=errors), 400
    ts = now_iso()
    cur = conn.execute(
        "INSERT INTO change_requests (device_id, device_name, title, reason, commands, rollback, verify, impact, "
        "probability, min_impact, risk_score, risk_level, risk_reasons, approvals_required, window_start, "
        "window_end, status, requested_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'borrador', ?, ?, ?)",
        (v["device_id"], v["device_name"], v["title"], v["reason"], v["commands"], v["rollback"], v["verify"],
         v["impact"], v["probability"], v["min_impact"], v["risk_score"], v["risk_level"], v["risk_reasons"],
         v["approvals_required"], v["window_start"], v["window_end"], user, ts, ts))
    conn.commit()
    audit(conn, user, "change.create", "change_requests", cur.lastrowid,
          f"{v['device_name']}: '{v['title']}' riesgo {v['risk_level']} ({v['risk_score']})")
    return jsonify(_public(get_change(conn, cur.lastrowid))), 201


@bp.get("/<int:cid>")
def change_detail(cid):
    conn = get_db()
    row = get_change(conn, cid)
    if row is None:
        return jsonify(errors=["Cambio no encontrado"]), 404
    d = _public(row)
    d["warnings"] = _overlaps(conn, row)
    # Fase 10.3: revisiones y pasos de la ejecución
    d["approvals"] = [dict(r) for r in conn.execute(
        "SELECT reviewer, decision, comment, decided_at FROM change_approvals WHERE change_id = ? ORDER BY id",
        (cid,))]
    d["execution"] = json.loads(row["execution"]) if row["execution"] else []
    d["baseline"] = None
    if row["baseline_version_id"]:
        b = conn.execute("SELECT id, version_no, captured_at, sha256 FROM config_versions WHERE id = ?",
                         (row["baseline_version_id"],)).fetchone()
        d["baseline"] = dict(b) if b else None
    return jsonify(d)


@bp.put("/<int:cid>")
def update_change(cid):
    conn = get_db()
    row = get_change(conn, cid)
    if row is None:
        return jsonify(errors=["Cambio no encontrado"]), 404
    if row["status"] != "borrador":
        return jsonify(errors=["Solo se edita en borrador: una vez enviado, el cambio aprobado debe ser "
                               "exactamente el revisado"]), 409
    if not _is_owner_or_admin(row, owner_only=True):
        return jsonify(errors=["Solo quien creó el cambio puede editarlo"]), 403
    v, errors = validate(conn, request.get_json(silent=True) or {}, actor())
    if errors:
        return jsonify(errors=errors), 400
    conn.execute(
        "UPDATE change_requests SET device_id = ?, device_name = ?, title = ?, reason = ?, commands = ?, "
        "rollback = ?, verify = ?, impact = ?, probability = ?, min_impact = ?, risk_score = ?, risk_level = ?, "
        "risk_reasons = ?, approvals_required = ?, window_start = ?, window_end = ?, updated_at = ? WHERE id = ?",
        (v["device_id"], v["device_name"], v["title"], v["reason"], v["commands"], v["rollback"], v["verify"],
         v["impact"], v["probability"], v["min_impact"], v["risk_score"], v["risk_level"], v["risk_reasons"],
         v["approvals_required"], v["window_start"], v["window_end"], now_iso(), cid))
    conn.commit()
    audit(conn, actor(), "change.update", "change_requests", cid,
          f"'{v['title']}' riesgo {v['risk_level']} ({v['risk_score']})")
    return jsonify(_public(get_change(conn, cid)))


@bp.post("/<int:cid>/submit")
def submit_change(cid):
    conn = get_db()
    row = get_change(conn, cid)
    if row is None:
        return jsonify(errors=["Cambio no encontrado"]), 404
    if row["status"] != "borrador":
        return jsonify(errors=[f"Solo se envía un borrador (estado actual: {row['status']})"]), 409
    if not _is_owner_or_admin(row, owner_only=True):
        return jsonify(errors=["Solo quien creó el cambio puede enviarlo a aprobación"]), 403
    # Se revalida al enviar: la ventana pudo vencerse o el inventario cambiar desde el borrador
    data = dict(row)
    for k in ("window_start", "window_end"):
        if data[k]:
            data[k] = datetime.strptime(data[k], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc).astimezone(local_tz()).strftime("%Y-%m-%dT%H:%M")
    v, errors = validate(conn, data, actor())
    if errors:
        return jsonify(errors=["No se puede enviar:"] + errors), 400
    base = conn.execute("SELECT id FROM config_versions WHERE device_id = ? ORDER BY version_no DESC LIMIT 1",
                        (row["device_id"],)).fetchone()
    ts = now_iso()
    conn.execute("UPDATE change_requests SET status = 'pendiente', submitted_at = ?, updated_at = ?, "
                 "baseline_version_id = ? WHERE id = ?", (ts, ts, base["id"] if base else None, cid))
    conn.commit()
    row = get_change(conn, cid)
    warnings = _overlaps(conn, row)
    if base is None:
        warnings.append("El equipo no tiene versión de configuración guardada: tome una línea base "
                        "(Inventario -> Config.) antes de ejecutar")
    audit(conn, actor(), "change.submit", "change_requests", cid,
          f"{row['device_name']}: '{row['title']}' riesgo {row['risk_level']} -> requiere "
          f"{row['approvals_required']} aprobación(es)" + (f" · {len(warnings)} aviso(s)" if warnings else ""))
    d = _public(row)
    d["warnings"] = warnings
    return jsonify(d)


@bp.post("/<int:cid>/cancel")
def cancel_change(cid):
    conn = get_db()
    row = get_change(conn, cid)
    if row is None:
        return jsonify(errors=["Cambio no encontrado"]), 404
    if row["status"] not in ("borrador", "pendiente", "aprobado"):
        return jsonify(errors=[f"No se puede cancelar un cambio en estado {row['status']}"]), 409
    if not _is_owner_or_admin(row):
        return jsonify(errors=["Solo quien lo creó o un administrador de seguridad puede cancelarlo"]), 403
    reason = str((request.get_json(silent=True) or {}).get("reason") or "").strip()
    if not 5 <= len(reason) <= 300:
        return jsonify(errors=["Motivo de la cancelación: entre 5 y 300 caracteres"]), 400
    ts = now_iso()
    conn.execute("UPDATE change_requests SET status = 'cancelado', cancel_reason = ?, closed_at = ?, "
                 "updated_at = ? WHERE id = ?", (reason, ts, ts, cid))
    conn.commit()
    audit(conn, actor(), "change.cancel", "change_requests", cid, f"'{row['title']}': {reason}")
    return jsonify(_public(get_change(conn, cid)))
