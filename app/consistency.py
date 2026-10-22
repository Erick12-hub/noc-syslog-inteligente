"""
Fase 9.5: chequeo de CONSISTENCIA de la red y del propio NOC.

    GET  /api/consistency        Hallazgos y reloj de cada equipo (solo lectura)
    POST /api/consistency/run    Revisa, audita y abre incidentes si hace falta

Qué revisa (cada hallazgo trae gravedad y una sugerencia):
  1. Reloj desfasado (NTP): compara la hora que trae cada evento con la hora en
     que el NOC lo recibió. Mediana de los últimos eventos del equipo.
         aviso   > NTP_WARN_SECONDS (2 s)      crítico > NTP_CRIT_SECONDS (60 s)
     Caso real del laboratorio (21-oct): el router quedó 5 h atrás por poner
     la hora antes que la zona, y el switch arrancó en 1993.
  2. Equipo sin eventos: silencioso más de CONSISTENCY_SILENT_HOURS, o un equipo
     REAL que nunca ha enviado eventos (revise "logging host").
  3. Interfaz desconocida y marca inconsistente en las últimas 24 h.
  4. IP del inventario que no está en ninguna interfaz que reporta el equipo
     (Fase 9.3): su Syslog llegaría con otra IP de origen y se rechazaría.
  5. IP duplicada entre equipos (interfaces leídas del equipo o inventario).
  6. Cadena de la auditoría (Fase 8.2). Si se rompe, POST /run y el receptor
     (cada CONSISTENCY_INTERVAL_MINUTES) abren un incidente de SEVERIDAD 1.
"""
import statistics
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify

from .auth import actor
from .config import Config
from .db import audit, get_db, verify_audit_chain
from .incidents import create_incident

bp = Blueprint("consistency", __name__, url_prefix="/api/consistency")

ORDER = {"critico": 0, "aviso": 1, "info": 2}
CHAIN_KEY = "consistencia|auditoria_cadena"
CLOCK_SAMPLES = 20


def _parse(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def human(seconds: float) -> str:
    """3.2 -> '3 s' · 18000 -> '5 h 0 min' · 1.06e9 -> '34 años' (switch con reloj de 1993)."""
    s = abs(seconds)
    if s < 60:
        return f"{s:.0f} s"
    if s < 3600:
        return f"{s // 60:.0f} min {s % 60:.0f} s"
    if s < 86400 * 2:
        return f"{s // 3600:.0f} h {s % 3600 // 60:.0f} min"
    if s < 86400 * 365:
        return f"{s // 86400:.0f} días"
    return f"{s / (86400 * 365.25):.0f} años"


# ---------------------------------------------------------------------------
# 1. Reloj de cada equipo
# ---------------------------------------------------------------------------
def clock_status(conn, device_id: int) -> dict:
    """
    offset = recibido - hora del evento (segundos), mediana de los últimos eventos.
    Positivo: el reloj del equipo está ATRASADO. Negativo: ADELANTADO.
    La mediana evita que un evento aislado (o con latencia) cambie el resultado.
    """
    rows = conn.execute(
        "SELECT received_at, event_time_utc FROM syslog_events WHERE device_id = ? "
        "AND event_time_utc IS NOT NULL ORDER BY id DESC LIMIT ?", (device_id, CLOCK_SAMPLES)).fetchall()
    if not rows:
        return {"samples": 0, "offset_s": None, "status": "sin_datos",
                "text": "Sin eventos con fecha: no se puede medir"}
    offsets = [(_parse(r["received_at"]) - _parse(r["event_time_utc"])).total_seconds() for r in rows]
    off = statistics.median(offsets)
    status = ("critico" if abs(off) > Config.NTP_CRIT_SECONDS
              else "aviso" if abs(off) > Config.NTP_WARN_SECONDS else "ok")
    if status == "ok":
        text = f"Sincronizado (desfase {human(off)})"
    else:
        text = f"Reloj {'atrasado' if off > 0 else 'adelantado'} {human(off)}"
    return {"samples": len(rows), "offset_s": round(off, 1), "status": status, "text": text}


# ---------------------------------------------------------------------------
# 2. Los chequeos
# ---------------------------------------------------------------------------
def _finding(severity, check, device, detail, suggestion):
    return {"severity": severity, "check": check,
            "device_id": device["id"] if device else None, "device": device["name"] if device else "NOC",
            "detail": detail, "suggestion": suggestion}


def run_checks(conn, now: datetime | None = None) -> dict:
    """Calcula los hallazgos SIN efectos (no audita ni crea incidentes)."""
    now = now or datetime.now(timezone.utc)
    since24 = _iso(now - timedelta(hours=24))
    silent_since = _iso(now - timedelta(hours=Config.CONSISTENCY_SILENT_HOURS))
    devices = conn.execute("SELECT * FROM devices ORDER BY name").fetchall()
    findings, clocks = [], []

    for d in devices:
        # --- 1. Reloj ---------------------------------------------------------
        c = clock_status(conn, d["id"])
        clocks.append({"device_id": d["id"], "device": d["name"], "is_simulated": d["is_simulated"], **c})
        if c["status"] in ("aviso", "critico"):
            if abs(c["offset_s"]) > 86400 * 365:      # el equipo arrancó sin hora (ej. 2960 en 1993)
                tip = ("El equipo no tiene la hora (arrancó con el reloj de fábrica): espere la "
                       "sincronización NTP ('show ntp status') o revise 'ntp server'")
            else:
                tip = ("Configure 'clock timezone' ANTES de 'clock set' y un servidor NTP; "
                       "verifique con 'show ntp status'")
            findings.append(_finding(c["status"], "reloj_desfasado", d,
                                     c["text"] + f" ({c['samples']} eventos)", tip))
        # --- 2. Silencio ------------------------------------------------------
        if d["authorized"] and d["status"] != "mantenimiento":
            last = conn.execute("SELECT MAX(received_at) FROM syslog_events WHERE device_id = ?",
                                (d["id"],)).fetchone()[0]
            if last is None and not d["is_simulated"]:
                findings.append(_finding("info", "sin_eventos", d, "Nunca ha enviado eventos al NOC",
                                         "Verifique 'logging host' y 'logging source-interface' en el equipo "
                                         "y la regla del firewall del PC"))
            elif last is not None and last < silent_since:
                findings.append(_finding("aviso", "sin_eventos", d,
                                         f"Sin eventos desde {last} (más de {Config.CONSISTENCY_SILENT_HOURS} h)",
                                         "Revise si el equipo está encendido y su configuración de Syslog"))
        # --- 3. Marcas de las últimas 24 h ----------------------------------------
        for flag, sev, text, tip in (
                ("interfaz_desconocida", "aviso", "eventos de interfaces no registradas",
                 "Lea las interfaces del equipo (Leer del equipo) o revise si el mensaje es fabricado"),
                ("marca_inconsistente", "aviso", "eventos con formato de otra marca",
                 "Verifique la marca en el inventario y descarte una suplantación de la IP")):
            n = conn.execute("SELECT COUNT(*) FROM syslog_events WHERE device_id = ? AND received_at >= ? "
                             "AND (',' || flags || ',') LIKE ?", (d["id"], since24, f"%,{flag},%")).fetchone()[0]
            if n:
                findings.append(_finding(sev, flag, d, f"{n} {text} en 24 h", tip))
        # --- 4. IP del inventario vs. interfaces reales ------------------------
        real_ips = [r["ip_address"] for r in conn.execute(
            "SELECT ip_address FROM interfaces WHERE device_id = ? AND source = 'equipo' "
            "AND ip_address IS NOT NULL", (d["id"],))]
        if real_ips and d["ip"] not in real_ips:
            findings.append(_finding("aviso", "ip_inventario", d,
                                     f"La IP del inventario ({d['ip']}) no está en ninguna interfaz del equipo "
                                     f"({', '.join(real_ips)})",
                                     "Corrija el inventario o la configuración: el Syslog llegaría con otra IP "
                                     "de origen y el NOC lo trataría como fuente desconocida"))

    # --- 5. IP duplicada entre equipos ----------------------------------------
    owners = {}
    for r in conn.execute("SELECT d.id, d.name, d.ip FROM devices d"):
        owners.setdefault(r["ip"], set()).add((r["id"], r["name"]))
    for r in conn.execute("SELECT i.ip_address, d.id, d.name FROM interfaces i JOIN devices d ON d.id = i.device_id "
                          "WHERE i.ip_address IS NOT NULL"):
        owners.setdefault(r["ip_address"], set()).add((r["id"], r["name"]))
    for ip, devs in sorted(owners.items()):
        if len(devs) > 1:
            names = sorted(n for _, n in devs)
            findings.append({"severity": "critico", "check": "ip_duplicada", "device_id": None,
                             "device": ", ".join(names), "detail": f"La IP {ip} aparece en {len(devs)} equipos",
                             "suggestion": "Un conflicto de IP corta la gestión y puede ser una suplantación: "
                                           "revise la configuración de ambos equipos"})

    # --- 6. Cadena de la auditoría ---------------------------------------------
    chain = verify_audit_chain(conn)
    if not chain["ok"]:
        findings.append({"severity": "critico", "check": "auditoria_cadena", "device_id": None, "device": "NOC",
                         "detail": f"Cadena de auditoría ROTA en el registro {chain['broken_at']}: {chain['reason']}",
                         "suggestion": "No modifique la base. Compare con el hash ancla de la bitácora y escale "
                                       "al administrador de seguridad"})

    findings.sort(key=lambda f: (ORDER[f["severity"]], f["device"], f["check"]))
    counts = {k: sum(1 for f in findings if f["severity"] == k) for k in ORDER}
    return {"checked_at": _iso(now), "findings": findings, "counts": counts, "clocks": clocks,
            "chain": {"ok": chain["ok"], "total": chain["total"], "broken_at": chain["broken_at"]}}


def run_consistency(conn, user: str, now: datetime | None = None) -> dict:
    """Revisión CON efectos: audita y, si la cadena está rota, abre un incidente de severidad 1."""
    result = run_checks(conn, now)
    incident = None
    if not result["chain"]["ok"]:
        open_inc = conn.execute("SELECT id FROM incidents WHERE correlation_key = ? AND status != 'cerrado'",
                                (CHAIN_KEY,)).fetchone()
        if open_inc is None:                  # uno solo mientras siga abierto
            incident = create_incident(
                conn, title="Integridad de la auditoría: cadena rota", severity=1, created_by="sistema",
                description=(f"La verificación automática encontró la cadena rota en el registro "
                             f"{result['chain']['broken_at']}. Posible alteración o borrado de registros."),
                correlation_key=CHAIN_KEY)
        else:
            incident = open_inc["id"]
    c = result["counts"]
    audit(conn, user, "consistency.run", None, None,
          f"criticos={c['critico']} avisos={c['aviso']} info={c['info']} cadena={'ok' if result['chain']['ok'] else 'ROTA'}"
          + (f" incidente={incident}" if incident else ""),
          "alerta" if c["critico"] else "ok")
    result["incident"] = incident
    return result


@bp.get("")
def consistency():
    return jsonify(run_checks(get_db()))


@bp.post("/run")
def consistency_run():
    return jsonify(run_consistency(get_db(), actor()))
