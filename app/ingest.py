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
    7. Si es sospechoso        -> registro en auditoría

Lo usan los tres orígenes: receptor UDP, importación de archivos y simulador.
"""
from datetime import datetime, timedelta, timezone

from .db import audit, now_iso
from .security import detect_prompt_injection, fingerprint
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
        return {"id": previous["id"], "duplicate": True, "dup_count": previous["dup_count"] + 1,
                "severity": p["severity"], "severity_name": p["severity_name"],
                "vendor": vendor, "device": device["name"] if device else None,
                "message": p["message"], "flags": flags}

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

    return {"id": event_id, "duplicate": False, "dup_count": 1,
            "severity": p["severity"], "severity_name": p["severity_name"],
            "vendor": vendor, "device": device["name"] if device else None,
            "message": p["message"], "flags": flags}


def import_lines(conn, lines, source_ip: str, actor: str, filename: str = "") -> dict:
    """
    Importa un archivo de log: una línea = un mensaje.
    Ignora líneas vacías y comentarios (#). Máximo MAX_IMPORT_LINES líneas.
    """
    stats = {"leidas": 0, "nuevas": 0, "duplicadas": 0, "ignoradas": 0}
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
    audit(conn, actor, "syslog.import", "syslog_events", None,
          f"archivo={filename or '-'} origen={source_ip} {stats}")
    return stats
