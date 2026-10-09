"""
Ingesta de eventos: el camino que sigue cada mensaje Syslog hasta la base de datos.

    mensaje crudo
       |
       v
    1. parse()                 -> facility, severidad, fabricante, mensaje
    2. ¿IP en el inventario?   -> asocia el equipo
    3. ¿Equipo autorizado?     -> lista permitida de fuentes
    4. ¿Prompt injection?      -> marca (NO ejecuta nada)
    5. ¿Repetido en 60 s?      -> deduplica (suma al contador)
    6. Guarda en syslog_events
    0. (solo UDP) ¿La fuente supera el límite por minuto? -> se descarta (tormenta)
    7. Si es sospechoso        -> registro en auditoría
    8. Severidad 0-3 + fuente autorizada -> incidente (o se correlaciona)
    9. Reglas de detección (app/rules.py) -> marcas e incidentes de seguridad

Lo usan los tres orígenes: receptor UDP, importación de archivos y simulador.
"""
from datetime import datetime, timedelta, timezone

from .config import Config
from .db import audit, now_iso
from .incidents import auto_incident_from_event, create_incident
from .rules import apply_rule_hits, evaluate, info_flags
from .security import STORM, detect_prompt_injection, fingerprint
from .syslog_parser import parse

DEDUP_WINDOW_SECONDS = 60
MAX_IMPORT_LINES = 5000


def _iso_seconds_ago(seconds: int) -> str:
    t = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def ingest(conn, raw: str, source_ip: str, origin: str, is_simulated: bool = False) -> dict:
    """
    Procesa y guarda UN mensaje. Devuelve un resumen del resultado.

    origin: 'udp' | 'importacion' | 'simulador'
    """
    # --- 0. Control de tormentas (solo tráfico de red en vivo) --------------
    if origin == "udp":
        allowed, first_excess = STORM.hit(source_ip, Config.STORM_MAX_PER_MINUTE)
        if not allowed:
            if first_excess:
                _storm_alert(conn, source_ip)
            return {"id": None, "duplicate": False, "dropped": True, "dup_count": 0,
                    "severity": None, "severity_name": "-", "vendor": "-", "device": None,
                    "message": "(descartado por control de tormentas)", "flags": ["tormenta"],
                    "incident": None}

    p = parse(raw)
    flags = list(p["parse_flags"])

    # --- 2 y 3. Equipo del inventario y lista permitida --------------------
    device = conn.execute(
        "SELECT id, name, vendor, authorized, is_simulated FROM devices WHERE ip = ?",
        (source_ip,)).fetchone()
    if device is None:
        flags.append("equipo_desconocido")
        authorized = False
    else:
        authorized = bool(device["authorized"])
        is_simulated = is_simulated or bool(device["is_simulated"])
    if not authorized:
        flags.append("fuente_no_autorizada")

    # Fabricante: el del inventario; si es "Otro"/desconocido, el que se
    # detectó en el texto; si no, "Desconocido".
    if device is not None and device["vendor"] != "Otro":
        vendor = device["vendor"]
    else:
        vendor = p["vendor_hint"] or "Desconocido"

    # --- 4. Prompt injection (solo se MARCA) --------------------------------
    if detect_prompt_injection(p["message"]):
        flags.append("posible_prompt_injection")
    flags += info_flags(p["message"], p["mnemonic"])   # login_fallido, cambio_config

    # --- 5. Deduplicación ---------------------------------------------------
    fp = fingerprint(source_ip, p["severity"], p["mnemonic"], p["message"])
    previous = conn.execute(
        "SELECT id, dup_count FROM syslog_events "
        "WHERE fingerprint = ? AND received_at >= ? ORDER BY id DESC LIMIT 1",
        (fp, _iso_seconds_ago(DEDUP_WINDOW_SECONDS))).fetchone()
    if previous:
        conn.execute("UPDATE syslog_events SET dup_count = dup_count + 1 WHERE id = ?",
                     (previous["id"],))
        conn.commit()
        # Las reglas también corren con los duplicados: 6 fallos de login
        # idénticos son 1 fila, pero siguen siendo un ataque de fuerza bruta.
        rule_ctx = {"id": previous["id"], "source_ip": source_ip, "message": p["message"],
                    "mnemonic": p["mnemonic"], "authorized": authorized, "is_simulated": is_simulated,
                    "device_id": device["id"] if device else None,
                    "device_name": device["name"] if device else None}
        hits = evaluate(conn, rule_ctx)
        rule_incidents = apply_rule_hits(conn, rule_ctx, hits)
        return {"id": previous["id"], "duplicate": True, "dup_count": previous["dup_count"] + 1,
                "severity": p["severity"], "severity_name": p["severity_name"],
                "vendor": vendor, "device": device["name"] if device else None,
                "message": p["message"], "flags": flags + hits, "incident": None,
                "rules": rule_incidents}

    # --- 6. Guardar ---------------------------------------------------------
    cur = conn.execute(
        "INSERT INTO syslog_events (received_at, event_time, source_ip, device_id, vendor, "
        "facility, severity, hostname, app_name, message, raw, origin, authorized_source, "
        "mnemonic, flags, fingerprint, dup_count, is_simulated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
        (now_iso(), p["event_time"], source_ip, device["id"] if device else None, vendor,
         p["facility"], p["severity"], p["hostname"], p["app_name"], p["message"],
         raw[:4000], origin, int(authorized), p["mnemonic"],
         ",".join(flags) or None, fp, int(is_simulated)))
    conn.commit()
    event_id = cur.lastrowid

    # --- 7. Auditoría de lo sospechoso -------------------------------------
    suspicious = [f for f in flags if f in ("fuente_no_autorizada", "posible_prompt_injection")]
    if suspicious:
        audit(conn, "sistema", "syslog.sospechoso", "syslog_events", event_id,
              f"origen={source_ip} marcas={','.join(suspicious)}", "alerta")

    # --- 8. Incidente automático / correlación ------------------------------
    incident = auto_incident_from_event(conn, {
        "id": event_id, "device_id": device["id"] if device else None,
        "device_name": device["name"] if device else None, "severity": p["severity"],
        "mnemonic": p["mnemonic"], "fingerprint": fp, "flags": flags,
        "authorized": authorized, "is_simulated": is_simulated})

    # --- 9. Reglas de detección ---------------------------------------------
    rule_ctx = {"id": event_id, "source_ip": source_ip, "message": p["message"],
                "mnemonic": p["mnemonic"], "authorized": authorized, "is_simulated": is_simulated,
                "device_id": device["id"] if device else None,
                "device_name": device["name"] if device else None}
    hits = evaluate(conn, rule_ctx)
    rule_incidents = apply_rule_hits(conn, rule_ctx, hits)
    if hits:
        audit(conn, "sistema", "regla.deteccion", "syslog_events", event_id,
              f"reglas={','.join(hits)} origen={source_ip}", "alerta")

    return {"id": event_id, "duplicate": False, "dup_count": 1,
            "severity": p["severity"], "severity_name": p["severity_name"],
            "vendor": vendor, "device": device["name"] if device else None,
            "message": p["message"], "flags": flags + hits, "incident": incident,
            "rules": rule_incidents}


def _storm_alert(conn, source_ip: str):
    """Primera vez que una fuente supera el límite en la ventana: auditar e informar."""
    audit(conn, "sistema", "syslog.tormenta", "devices", None,
          f"origen={source_ip} supera {Config.STORM_MAX_PER_MINUTE} mensajes/min; "
          f"se descarta el exceso", "alerta")
    device = conn.execute("SELECT id, name, authorized, is_simulated FROM devices WHERE ip = ?",
                          (source_ip,)).fetchone()
    if device and device["authorized"]:
        key = f"tormenta|{device['id']}"
        if not conn.execute("SELECT 1 FROM incidents WHERE correlation_key = ? AND status != 'cerrado'",
                            (key,)).fetchone():
            create_incident(conn, title=f"Tormenta de eventos desde {device['name']}", severity=2,
                            created_by="sistema", device_id=device["id"], correlation_key=key,
                            is_simulated=bool(device["is_simulated"]),
                            description=(f"La fuente superó {Config.STORM_MAX_PER_MINUTE} mensajes por "
                                         f"minuto. El exceso se descartó para proteger al NOC."))


def import_lines(conn, lines, source_ip: str, actor: str, filename: str = "") -> dict:
    """
    Importa un archivo de log: una línea = un mensaje.
    Ignora líneas vacías y comentarios (#). Máximo MAX_IMPORT_LINES líneas.
    """
    stats = {"leidas": 0, "nuevas": 0, "duplicadas": 0, "ignoradas": 0, "incidentes_nuevos": 0}
    for line in lines:
        if stats["leidas"] >= MAX_IMPORT_LINES:
            break
        line = line.strip()
        if not line or line.startswith("#"):
            stats["ignoradas"] += 1
            continue
        stats["leidas"] += 1
        r = ingest(conn, line, source_ip, "importacion")
        stats["duplicadas" if r["duplicate"] else "nuevas"] += 1
        if r.get("incident") and not r["incident"]["correlated"]:
            stats["incidentes_nuevos"] += 1
    audit(conn, actor, "syslog.import", "syslog_events", None,
          f"archivo={filename or '-'} origen={source_ip} {stats}")
    return stats
