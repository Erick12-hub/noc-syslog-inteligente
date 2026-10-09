"""
Reglas de detección (Fase 4): convierten patrones de eventos en alertas.

Cada regla mira datos ESTRUCTURADOS del evento (código del fabricante, usuario,
comando, hora) y nunca obedece al texto del log. Si una regla se cumple:
  - se agrega una marca (flag) al evento, y
  - si la fuente está autorizada, se abre (o se correlaciona) un incidente.

    Regla                    Qué detecta                                      Sev. incidente
    ----------------------   ----------------------------------------------   --------------
    fuerza_bruta             >= 5 inicios de sesión fallidos en 2 minutos     2 Critical
    cambio_fuera_de_horario  cambio de configuración fuera del horario         3 Error
                             laboral o en fin de semana
    cuenta_servicio          una cuenta de servicio (svc_*) cambia la          2 Critical
                             configuración (las cuentas de servicio no
                             deberían hacer cambios manuales)
    logs_deshabilitados      alguien apaga el envío de logs (clásico de un     1 Alert
                             atacante que quiere borrar sus huellas)

Los umbrales se configuran en .env (ver app/config.py).
"""
import re
from datetime import datetime, timedelta, timezone

from .config import Config
from .db import now_iso

BRUTE_FORCE_THRESHOLD = 5
BRUTE_FORCE_WINDOW_SECONDS = 120

# --- Patrones (se aplican sobre el mensaje ya limpio y el código) ----------
RE_LOGIN_FAILED = re.compile(
    r"login failed|LOGIN_FAILED|authentication fail|invalid password|failed password", re.I)
RE_CONFIG_CODES = re.compile(r"SYS-5-CONFIG_I|SHELL/5/CMDRECORD|logid=0100044547")
RE_HUAWEI_COMMAND = re.compile(r'Command="([^"]*)"')
RE_READ_ONLY_CMD = re.compile(r"^\s*(display|show|get|ping|tracert|traceroute|dir)\b", re.I)
RE_USER = re.compile(r'(?:\bby\s+|User=|user=")\s*"?([\w.\-]+)')
RE_LOGS_OFF = re.compile(
    r"undo info-center enable|no logging (?:host|on|trap)|logging off|"
    r"syslogd.*set status disable|set status disable", re.I)

RULES = {
    "fuerza_bruta":            (2, "Posible fuerza bruta en {device}"),
    "cambio_fuera_de_horario": (3, "Cambio de configuración fuera de horario en {device}"),
    "cuenta_servicio":         (2, "Cuenta de servicio cambiando la configuración en {device}"),
    "logs_deshabilitados":     (1, "Registro de logs deshabilitado en {device}"),
}


def is_login_failure(message: str, mnemonic: str | None) -> bool:
    return bool(RE_LOGIN_FAILED.search(f"{mnemonic or ''} {message}"))


def is_config_change(message: str, mnemonic: str | None) -> bool:
    """Un cambio de configuración (los comandos de solo lectura no cuentan)."""
    if not RE_CONFIG_CODES.search(mnemonic or "") and "Configured from" not in message:
        return False
    cmd = RE_HUAWEI_COMMAND.search(message)
    if cmd and RE_READ_ONLY_CMD.match(cmd.group(1)):
        return False   # Huawei registra TODOS los comandos; "display ..." no cambia nada
    return True


def extract_user(message: str) -> str | None:
    m = RE_USER.search(message)
    return m.group(1) if m else None


def outside_business_hours(now_utc: datetime) -> bool:
    """True si la hora local está fuera del horario laboral o es fin de semana."""
    local = now_utc + timedelta(hours=Config.LOCAL_UTC_OFFSET)
    start, end = (int(x) for x in Config.BUSINESS_HOURS.split("-"))
    return local.weekday() >= 5 or not (start <= local.hour < end)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def evaluate(conn, ev: dict, now: datetime | None = None) -> list[str]:
    """
    Evalúa las reglas sobre un evento y devuelve la lista de reglas cumplidas.

    ev: id, source_ip, message, mnemonic (todo ya procesado por el parser).
    'now' permite a las pruebas simular una hora concreta.
    """
    now = now or datetime.now(timezone.utc)
    hits = []

    if is_login_failure(ev["message"], ev["mnemonic"]):
        # Se suman las repeticiones (dup_count) de los fallos de esta fuente
        # en la ventana: la deduplicación agrupa, pero no esconde el volumen.
        total = conn.execute(
            "SELECT COALESCE(SUM(dup_count), 0) FROM syslog_events WHERE source_ip = ? "
            "AND received_at >= ? AND (',' || COALESCE(flags,'') || ',') LIKE '%,login_fallido,%'",
            (ev["source_ip"], _iso(now - timedelta(seconds=BRUTE_FORCE_WINDOW_SECONDS)))).fetchone()[0]
        if total >= BRUTE_FORCE_THRESHOLD:
            hits.append("fuerza_bruta")

    if is_config_change(ev["message"], ev["mnemonic"]):
        if outside_business_hours(now):
            hits.append("cambio_fuera_de_horario")
        user = extract_user(ev["message"])
        if user and user.startswith(Config.SERVICE_ACCOUNT_PREFIXES):
            hits.append("cuenta_servicio")

    if RE_LOGS_OFF.search(ev["message"]):
        hits.append("logs_deshabilitados")
    return hits


def info_flags(message: str, mnemonic: str | None) -> list[str]:
    """Marcas informativas que se guardan con el evento para que las reglas cuenten."""
    flags = []
    if is_login_failure(message, mnemonic):
        flags.append("login_fallido")
    if is_config_change(message, mnemonic):
        flags.append("cambio_config")
    return flags


def apply_rule_hits(conn, ev: dict, hits: list[str]) -> list[dict]:
    """
    Agrega las marcas al evento y abre/correlaciona un incidente por regla
    (solo si la fuente está autorizada, igual que la política de severidad).
    """
    from .incidents import create_incident   # import tardío: evita importación circular
    if not hits:
        return []
    row = conn.execute("SELECT flags FROM syslog_events WHERE id = ?", (ev["id"],)).fetchone()
    current = [f for f in (row["flags"] or "").split(",") if f]
    conn.execute("UPDATE syslog_events SET flags = ? WHERE id = ?",
                 (",".join(dict.fromkeys(current + hits)), ev["id"]))
    conn.commit()

    results = []
    if not ev["authorized"]:
        return results
    for rule in hits:
        severity, title = RULES[rule]
        key = f"regla|{rule}|{ev['device_id']}"
        open_inc = conn.execute(
            "SELECT id FROM incidents WHERE correlation_key = ? AND status != 'cerrado'",
            (key,)).fetchone()
        if open_inc:
            conn.execute("UPDATE incidents SET event_count = event_count + 1, last_event_at = ?, "
                         "updated_at = ? WHERE id = ?", (now_iso(), now_iso(), open_inc["id"]))
            conn.commit()
            results.append({"rule": rule, "id": open_inc["id"], "correlated": True})
        else:
            inc_id = create_incident(
                conn, title=title.format(device=ev["device_name"] or ev["source_ip"]),
                severity=severity, created_by="sistema", device_id=ev["device_id"],
                event_id=ev["id"], correlation_key=key, is_simulated=ev["is_simulated"],
                description=(f"Generado por la regla de detección '{rule}' (evento #{ev['id']}). "
                             f"Ver docs/04_politica_ia.md."))
            results.append({"rule": rule, "id": inc_id, "correlated": False})
    return results
