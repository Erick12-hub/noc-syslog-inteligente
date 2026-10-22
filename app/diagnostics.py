"""
Fase 9.4: diagnóstico DESDE el equipo (ping y traceroute).

    POST /api/devices/<id>/diagnostic   {"type": "ping", "target": "192.168.100.10"}

El comando lo ejecuta el equipo (por consola o SSH, app/connector.py), no el PC
del NOC: así se prueba la ruta REAL que usa el equipo, por ejemplo para
enviarnos el Syslog.

CONTROLES (en este orden):
  1. Destino: solo una IPv4 válida, unicast y dentro de las REDES PERMITIDAS
     (privadas y de documentación por defecto). No se usan los equipos del
     laboratorio para sondear hosts de Internet.
  2. Límite de frecuencia: DIAG_MAX_PER_MINUTE por usuario y equipo. Un
     traceroute ocupa el puerto de consola varios segundos.
  3. El comando pasa además por la LISTA PERMITIDA de la consola: si alguien
     cambiara este módulo, la política seguiría bloqueando lo no permitido.
  4. Todo queda en la auditoría con el resultado resumido.
La IA puede SUGERIR un diagnóstico en una propuesta, pero no ejecutarlo.
"""
import ipaddress
import re

from flask import Blueprint, jsonify, request

from .auth import actor
from .config import Config
from .db import audit, get_db
from .security import RateLimiter

bp = Blueprint("diagnostics", __name__, url_prefix="/api/devices")

TYPES = ("ping", "traceroute")
# Comando por plataforma. {ip} ya validada.
COMMANDS = {
    "ping": {"cisco_ios": "ping {ip}", "cisco_xe": "ping {ip}",
             "huawei": "ping -c 5 {ip}", "fortinet": "execute ping {ip}"},
    "traceroute": {"cisco_ios": "traceroute {ip}", "cisco_xe": "traceroute {ip}",
                   "huawei": "tracert -m 15 -w 2000 {ip}", "fortinet": "execute traceroute {ip}"},
}
LIMITER = RateLimiter(window_seconds=60)


def _allowed_networks():
    return [ipaddress.ip_network(n.strip()) for n in Config.DIAG_ALLOWED_NETS.split(",") if n.strip()]


def validate_target(target: str) -> tuple[str | None, list[str]]:
    """Devuelve (ip_normalizada, errores)."""
    try:
        ip = ipaddress.IPv4Address(str(target or "").strip())
    except ValueError:
        return None, ["Destino inválido: escriba una dirección IPv4 (ej. 192.168.100.10)"]
    if ip.is_multicast or ip.is_unspecified or ip == ipaddress.IPv4Address("255.255.255.255"):
        return None, [f"Destino no permitido: {ip} no es una dirección de un solo equipo"]
    if not any(ip in net for net in _allowed_networks()):
        return None, [f"Destino fuera de las redes permitidas ({Config.DIAG_ALLOWED_NETS}): "
                      "no se usan los equipos para sondear Internet"]
    return str(ip), []


# ---------------------------------------------------------------------------
# Lectura de resultados (la salida del equipo es un DATO NO CONFIABLE: solo
# se extraen números con patrones fijos)
# ---------------------------------------------------------------------------
RE_CISCO_PING = re.compile(r"Success rate is (\d+) percent \((\d+)/(\d+)\)"
                           r"(?:, round-trip min/avg/max = (\d+)/(\d+)/(\d+) ms)?")
# Fortinet: "5 packets transmitted, 5 packets received" · Huawei: en dos líneas, sin coma
RE_GENERIC_PING = re.compile(r"(\d+) packet\(?s?\)? transmitted,?\s*(\d+) (?:packet\(?s?\)? )?received")
RE_GENERIC_RTT = re.compile(r"round-trip min/avg/max = ([\d.]+)/([\d.]+)/([\d.]+) ms")
RE_HOP = re.compile(r"^\s*(\d{1,2})\s+(.*)$")
RE_IP = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
RE_MS = re.compile(r"([\d.]+)\s*ms(?:ec)?")


def parse_ping(text: str) -> dict:
    m = RE_CISCO_PING.search(text or "")
    if m:
        sent, ok = int(m[3]), int(m[2])
        avg = int(m[5]) if m[5] else None
    else:
        g = RE_GENERIC_PING.search(text or "")
        if not g:
            return {"recognized": False}
        sent, ok = int(g[1]), int(g[2])
        r = RE_GENERIC_RTT.search(text or "")
        avg = float(r[2]) if r else None
    return {"recognized": True, "sent": sent, "received": ok,
            "success_pct": round(100 * ok / sent) if sent else 0, "avg_ms": avg,
            "reachable": ok > 0}


def parse_traceroute(text: str, target: str) -> dict:
    hops = []
    for line in (text or "").splitlines():
        m = RE_HOP.match(line)
        if not m or "Tracing" in line or "traceroute to" in line.lower():
            continue
        rest = m[2]
        ip = RE_IP.search(rest)
        times = [float(t) for t in RE_MS.findall(rest)]
        hops.append({"hop": int(m[1]), "ip": ip[1] if ip else None,
                     "avg_ms": round(sum(times) / len(times), 1) if times else None})
    return {"recognized": bool(hops), "hops": hops,
            "reached": any(h["ip"] == target for h in hops)}


def summary_text(kind: str, target: str, result: dict) -> str:
    if not result.get("recognized"):
        return f"{kind} {target}: salida no reconocida (ver la salida completa)"
    if kind == "ping":
        avg = f", promedio {result['avg_ms']} ms" if result["avg_ms"] is not None else ""
        return f"ping {target}: {result['success_pct']}% ({result['received']}/{result['sent']}){avg}"
    return (f"traceroute {target}: {len(result['hops'])} saltos, "
            f"{'llegó al destino' if result['reached'] else 'NO llegó al destino'}")


def run_diagnostic(conn, device, kind: str, target: str, user: str) -> tuple[dict, int]:
    from .connector import run_session          # import tardío: evita importaciones circulares
    errors = []
    if kind not in TYPES:
        errors.append(f"Tipo inválido. Opciones: {', '.join(TYPES)}")
    ip, target_errors = validate_target(target)
    errors += target_errors
    command = COMMANDS.get(kind, {}).get(device["platform"])
    if kind in TYPES and command is None:
        errors.append("Elija la plataforma del equipo en el inventario")
    if errors:
        return {"errors": errors}, 400
    allowed, first = LIMITER.hit(f"{user}:{device['id']}", Config.DIAG_MAX_PER_MINUTE)
    if not allowed:
        if first:
            audit(conn, user, "device.diagnostic_limit", "devices", device["id"],
                  f"{device['name']}: más de {Config.DIAG_MAX_PER_MINUTE} diagnósticos por minuto", "bloqueado")
        return {"errors": [f"Límite de {Config.DIAG_MAX_PER_MINUTE} diagnósticos por minuto en este equipo. "
                           "Espere un momento"]}, 429
    command = command.format(ip=ip)
    session, status = run_session(conn, device, [command], user, diagnostic=True)
    if status != 200:
        return session, status
    output = next((c["output"] for c in session["commands"] if c["command"] == command), "")
    result = parse_ping(output) if kind == "ping" else parse_traceroute(output, ip)
    text = summary_text(kind, ip, result)
    ok = result.get("reachable") if kind == "ping" else result.get("reached")
    audit(conn, user, "device.diagnostic", "device_sessions", session["id"], f"{device['name']}: {text}",
          "ok" if ok else "alerta")
    return {"session": session["id"], "type": kind, "target": ip, "command": command,
            "result": result, "summary": text, "output": output,
            "serial_number": session["serial_number"], "warnings": session["warnings"]}, 200


@bp.post("/<int:device_id>/diagnostic")
def diagnostic(device_id):
    conn = get_db()
    device = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if device is None:
        return jsonify(error="Equipo no encontrado"), 404
    data = request.get_json(silent=True) or {}
    result, status = run_diagnostic(conn, device, str(data.get("type", "")), str(data.get("target", "")), actor())
    return jsonify(result), status
