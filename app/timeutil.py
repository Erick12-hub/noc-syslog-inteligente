"""
Utilidades de fecha y hora (Fase 7).

El NOC guarda todas las fechas en UTC (ej. 2026-10-16T17:30:00Z), pero el
operador piensa en HORA DE COLOMBIA (UTC-5). Este módulo hace la conversión en
un solo lugar para que filtros, reglas e informes usen el mismo criterio.

Se usa un desfase FIJO (Config.LOCAL_UTC_OFFSET) en vez de una zona con nombre
("America/Bogota") porque Colombia no tiene horario de verano y así no se
depende del paquete tzdata, que Windows no trae instalado.

Dos usos distintos de "fecha futura" (ver docs/contexto Corte 3):
  1. FILTRO: la fecha la escribe el operador  -> si es futura se RECHAZA (400).
  2. EVENTO: la fecha la envía el equipo      -> NO se rechaza; se guarda y se
     marca 'fecha_futura' porque indica un reloj desfasado (problema de NTP).
"""
import re
from datetime import date, datetime, time, timedelta, timezone

from .config import Config

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}

RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# RFC 3164: "Oct  5 10:15:42.551"  o, con año (Huawei), "Oct 5 2026 13:05:10"
RE_3164 = re.compile(
    r"^(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})(?:\s+(?P<year>\d{4}))?\s+"
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})")
# Fortinet: "2026-10-05 08:00:00"
RE_FORTI = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})$")


def local_tz() -> timezone:
    """Zona horaria del NOC como desfase fijo (Colombia = UTC-5)."""
    return timezone(timedelta(hours=Config.LOCAL_UTC_OFFSET))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def local_today(now: datetime | None = None) -> date:
    """La fecha de HOY en Colombia (a las 9 p. m. del 16 en Bogotá ya es el 17 en UTC)."""
    return (now or now_utc()).astimezone(local_tz()).date()


def to_iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_filter_date(value: str) -> date | None:
    """Convierte 'AAAA-MM-DD' en fecha. Devuelve None si el formato o la fecha no son válidos."""
    if not isinstance(value, str) or not RE_DATE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:          # p. ej. 2026-02-30
        return None


def local_day_bounds_utc(day: date) -> tuple[str, str]:
    """
    Primer y último segundo de un día de Colombia, expresados en UTC.

        16-oct 00:00:00 (Bogotá) = 16-oct 05:00:00Z
        16-oct 23:59:59 (Bogotá) = 17-oct 04:59:59Z
    """
    start = datetime.combine(day, time.min, tzinfo=local_tz())
    end = start + timedelta(days=1) - timedelta(seconds=1)
    return to_iso_utc(start), to_iso_utc(end)


def validate_date_range(desde: str | None, hasta: str | None,
                        now: datetime | None = None) -> tuple[list[str], dict]:
    """
    Valida el rango de fechas de un filtro.

    Reglas: formato AAAA-MM-DD, ninguna fecha posterior a HOY (hora de
    Colombia) y 'desde' no puede ser mayor que 'hasta'.
    Devuelve (errores, {"desde_utc": ..., "hasta_utc": ...}).
    """
    errors, bounds = [], {}
    today = local_today(now)
    parsed = {}
    for name, value in (("desde", desde), ("hasta", hasta)):
        if not value:
            continue
        d = parse_filter_date(value)
        if d is None:
            errors.append(f"Fecha '{name}' inválida: use el formato AAAA-MM-DD")
        elif d > today:
            errors.append(f"La fecha '{name}' ({d.isoformat()}) es posterior a hoy "
                          f"({today.isoformat()}, hora de Colombia). Solo se consultan hoy e histórico.")
        else:
            parsed[name] = d
    if "desde" in parsed and "hasta" in parsed and parsed["desde"] > parsed["hasta"]:
        errors.append("La fecha 'desde' no puede ser posterior a 'hasta'")
    if "desde" in parsed:
        bounds["desde_utc"] = local_day_bounds_utc(parsed["desde"])[0]
    if "hasta" in parsed:
        bounds["hasta_utc"] = local_day_bounds_utc(parsed["hasta"])[1]
    return errors, bounds


def event_time_to_utc(event_time: str | None, now: datetime | None = None) -> datetime | None:
    """
    Interpreta la fecha que trae el propio mensaje y la pasa a UTC.

    - RFC 5424 (ISO con zona): se respeta la zona del mensaje.
    - RFC 3164 y Fortinet (sin zona): se asume hora de Colombia. (En la Fase 9
      se usará la zona configurada para cada equipo del inventario.)
    - RFC 3164 sin año: se asume el año actual; si eso da más de 30 días en el
      futuro (mensaje del 31-dic recibido el 1-ene), se toma el año anterior.
    Devuelve None si no se puede interpretar (no es un error: el evento se guarda igual).
    """
    if not event_time:
        return None
    now = now or now_utc()
    text = event_time.strip()
    tz = local_tz()
    try:
        if "T" in text and (text.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", text)):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
        m = RE_FORTI.match(text)
        if m:
            return datetime.fromisoformat(f"{m[1]}T{m[2]}").replace(tzinfo=tz).astimezone(timezone.utc)
        m = RE_3164.match(text)
        if m and m["mon"] in MONTHS:
            year = int(m["year"]) if m["year"] else now.astimezone(tz).year
            dt = datetime(year, MONTHS[m["mon"]], int(m["day"]),
                          int(m["h"]), int(m["m"]), int(m["s"]), tzinfo=tz)
            if not m["year"] and dt - now > timedelta(days=30):
                dt = dt.replace(year=year - 1)
            return dt.astimezone(timezone.utc)
    except ValueError:          # fecha imposible, p. ej. Feb 30
        return None
    return None


def is_future(event_utc: datetime | None, received_utc: datetime,
              tolerance_s: int | None = None) -> bool:
    """¿La fecha del evento está más adelante que la hora de recepción (con tolerancia)?"""
    if event_utc is None:
        return False
    tol = Config.FUTURE_TOLERANCE_SECONDS if tolerance_s is None else tolerance_s
    return (event_utc - received_utc).total_seconds() > tol
