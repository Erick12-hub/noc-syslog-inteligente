"""
Consola tipo PuTTY SIMULADA, de solo lectura (RF-10).

    GET  /api/console/allowed?vendor=Cisco      Comandos permitidos
    POST /api/console  {device_id, command, actor}

IMPORTANTE: NO se conecta a ningún equipo. Las salidas se generan con los
datos del inventario y los eventos del NOC. La conexión real por SSH a través
de un backend autorizado corresponde al Corte 3.

POLÍTICA (en este orden; la primera que falla bloquea):
  1. El actor 'asistente_ia' NUNCA ejecuta comandos: solo puede PROPONER
     acciones, que un humano aprueba (ver app/proposals.py).
  2. Caracteres de encadenamiento o redirección (; | & ` $ > < y saltos de
     línea) se bloquean: evitan esconder un segundo comando detrás de uno
     permitido ("show clock ; reload").
  3. Comandos peligrosos conocidos (configure, reload, delete, erase...) se
     bloquean con una razón explícita.
  4. LISTA PERMITIDA: solo se ejecuta lo que coincide EXACTAMENTE con un patrón
     de solo lectura de ese fabricante. Todo lo demás se bloquea por defecto.
Cada intento, permitido o bloqueado, queda en la auditoría.
"""
import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, request

from .config import Config
from .db import audit, get_db

bp = Blueprint("console", __name__, url_prefix="/api/console")

MAX_COMMAND_LEN = 120
RE_META = re.compile(r"[;|&`$><\n\r\\]")

# Lista permitida: (patrón exacto, descripción). Solo lectura.
ALLOWLIST = {
    "Cisco": [
        (r"show version", "Versión de software y hardware"),
        (r"show clock", "Fecha y hora del equipo"),
        (r"show ip interface brief", "Estado resumido de interfaces"),
        (r"show logging", "Configuración de logging y últimos mensajes"),
        (r"show ntp associations", "Estado de sincronización NTP"),
        (r"show users", "Sesiones abiertas"),
    ],
    "Fortinet": [
        (r"get system status", "Versión y estado del sistema"),
        (r"get system performance status", "CPU y memoria"),
        (r"get log syslogd setting", "Configuración Syslog"),
        (r"diagnose sys ntp status", "Estado de sincronización NTP"),
        (r"get system interface physical", "Estado de interfaces"),
    ],
    "Huawei": [
        (r"display version", "Versión de software y hardware"),
        (r"display clock", "Fecha y hora del equipo"),
        (r"display ip interface brief", "Estado resumido de interfaces"),
        (r"display info-center", "Configuración del centro de información (Syslog)"),
        (r"display ntp-service status", "Estado de sincronización NTP"),
        (r"display users", "Sesiones abiertas"),
    ],
}
ALLOWLIST["Otro"] = []

# Comandos que modifican, reinician, borran o exponen secretos
DANGEROUS = [
    (r"^(conf(igure)?( t(erminal)?)?|system-view|config\b)", "entra a modo de configuración"),
    (r"^(reload|reboot|reset|execute (reboot|shutdown|factoryreset))", "reinicia el equipo"),
    (r"^(write erase|erase|delete|format|del\b|rmdir)", "borra información del equipo"),
    (r"^(copy|tftp|scp|ftp|execute (backup|restore))", "copia o transfiere archivos"),
    (r"^(shutdown|no |undo |set |unset |clear )", "modifica la configuración o el estado"),
    (r"^(debug|terminal monitor|tclsh|diagnose debug)", "consume recursos o abre un intérprete"),
    (r"^(username|password|enable secret|crypto key)", "maneja credenciales"),
    (r"^(show run(ning)?(-config)?|show startup|display current-configuration|show full-configuration)",
     "expone la configuración completa (con secretos); requiere aprobación"),
]


def _normalize(cmd: str) -> str:
    return re.sub(r"\s+", " ", cmd.strip()).lower()


def check(vendor: str, command: str, actor: str) -> tuple[bool, str]:
    """Aplica la política. Devuelve (permitido, motivo)."""
    if actor == "asistente_ia":
        return False, ("Un agente de IA no ejecuta comandos. Debe crear una PROPUESTA "
                       "que un operador humano revise y apruebe.")
    if not command.strip():
        return False, "Comando vacío"
    if len(command) > MAX_COMMAND_LEN:
        return False, f"Comando demasiado largo (máx. {MAX_COMMAND_LEN} caracteres)"
    if RE_META.search(command):
        return False, "Contiene caracteres de encadenamiento o redirección (; | & ` $ > <)"
    cmd = _normalize(command)
    for pattern, why in DANGEROUS:
        if re.match(pattern, cmd):
            return False, f"Comando peligroso: {why}"
    for pattern, _desc in ALLOWLIST.get(vendor, []):
        if re.fullmatch(pattern, cmd):
            return True, "Permitido (solo lectura)"
    return False, f"No está en la lista permitida de {vendor} (bloqueado por defecto)"


# ---------------------------------------------------------------------------
# Salidas SIMULADAS (construidas con datos del inventario y de los eventos)
# ---------------------------------------------------------------------------
def _local_now():
    return datetime.now(timezone.utc) + timedelta(hours=Config.LOCAL_UTC_OFFSET)


def simulate(conn, dev, cmd: str) -> str:
    cmd = _normalize(cmd)
    now = _local_now()
    name, ip, model, ver = dev["name"], dev["ip"], dev["model"] or "-", dev["version"] or "-"
    events = conn.execute(
        "SELECT received_at, severity, mnemonic, message FROM syslog_events WHERE device_id = ? "
        "ORDER BY id DESC LIMIT 5", (dev["id"],)).fetchall()
    ev_lines = [f"  {e['received_at']} sev{e['severity']} {e['mnemonic'] or ''} {e['message'][:70]}"
                for e in events] or ["  (sin eventos registrados para este equipo)"]
    clock = now.strftime("%H:%M:%S.000 COT %a %b %d %Y")
    up = "Up" if dev["status"] == "activo" else "down"

    out = {
        "show version": [f"Cisco IOS XE Software, Version {ver.split()[-1]}", f"{name} uptime is 12 days, 4 hours",
                         f"cisco {model} processor with 3.7G bytes of memory", "Configuration register is 0x2102"],
        "show clock": [f"*{clock}"],
        "show ip interface brief": ["Interface              IP-Address      OK? Method Status   Protocol",
                                    f"GigabitEthernet0/0/0   {ip:<15} YES NVRAM  up       {up}",
                                    "GigabitEthernet0/0/2   unassigned      YES unset  down     down"],
        "show logging": ["Syslog logging: enabled", "    Trap logging: level informational",
                         "        Logging to 192.0.2.250 (udp port 5514, audit disabled, link up)",
                         "Log Buffer (últimos eventos registrados en el NOC):"] + ev_lines,
        "show ntp associations": ["  address         ref clock       st   when   poll reach  delay  offset   disp",
                                  "*~192.0.2.123     .GNSS.           1     35     64   377  1.204   0.311  0.142",
                                  " * sys.peer, # selected, + candidate, - outlyer, x falseticker"],
        "show users": ["    Line       User       Host(s)              Idle       Location",
                       "*  2 vty 0     noc_admin  idle                 00:00:00 192.0.2.50"],
        "get system status": [f"Version: {model} {ver}", f"Hostname: {name}", "Operation Mode: NAT",
                              f"System time: {now:%a %b %d %H:%M:%S %Y}"],
        "get system performance status": ["CPU states: 3% user 1% system 0% nice 96% idle",
                                          "Memory: 1943604k total, 712040k used (36.6%)"],
        "get log syslogd setting": ["status              : enable", "server              : \"192.0.2.250\"",
                                    "mode                : udp", "port                : 5514",
                                    "facility            : local7"],
        "diagnose sys ntp status": ["synchronized: yes, ntpsync: enabled, server-mode: disabled",
                                    "ipv4 server(192.0.2.123) -- reachable(0xff) S:1 T:32 selected"],
        "get system interface physical": [f"    ==[wan1]  mode: static  ip: {ip} 255.255.255.0  status: {up}",
                                          "    ==[internal1]  mode: static  ip: 192.0.2.254 255.255.255.0  status: up"],
        "display version": [f"Huawei Versatile Routing Platform Software", f"VRP (R) software, {ver}",
                            f"HUAWEI {model} uptime is 12 days, 4 hours"],
        "display clock": [now.strftime("%Y-%m-%d %H:%M:%S-05:00"), "Time Zone(COT) : UTC-05:00"],
        "display ip interface brief": ["Interface                 IP Address/Mask    Physical  Protocol",
                                       f"GigabitEthernet0/0/0      {ip}/24{'':<4} {up:<9} {up}",
                                       "GigabitEthernet0/0/1      unassigned         down      down"],
        "display info-center": ["Information Center: enabled", "Log host:",
                                "  192.0.2.250 port 5514, channel number 2, channel name loghost,",
                                "  language english, facility local7, with source interface"] + ev_lines,
        "display ntp-service status": [" clock status: synchronized", " clock stratum: 2",
                                       " reference clock ID: 192.0.2.123"],
        "display users": ["  User-Intf    Delay    Type   Network Address     AuthenStatus",
                          "+ 129 VTY 0   00:00:00  SSH    192.0.2.50           pass"],
    }
    return "\n".join(["[SALIDA SIMULADA - no hay conexión con ningún equipo]"] + out.get(cmd, ["(sin salida)"]))


@bp.get("/allowed")
def allowed():
    vendor = request.args.get("vendor", "Cisco")
    return jsonify(vendor=vendor, allowed=[{"command": c, "description": d}
                                           for c, d in ALLOWLIST.get(vendor, [])])


@bp.post("")
def run():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    dev = conn.execute("SELECT * FROM devices WHERE id = ?", (data.get("device_id"),)).fetchone()
    if dev is None:
        return jsonify(errors=["Seleccione un equipo del inventario"]), 400
    command = str(data.get("command") or "")
    actor = "asistente_ia" if data.get("actor") == "asistente_ia" else current_app.config["DEFAULT_OPERATOR"]

    ok, reason = check(dev["vendor"], command, actor)
    audit(conn, actor, "console.allowed" if ok else "console.blocked", "devices", dev["id"],
          f"{dev['name']}: {command[:MAX_COMMAND_LEN]!r} -> {reason}", "ok" if ok else "bloqueado")
    if not ok:
        return jsonify(allowed=False, reason=reason, command=command), 403
    return jsonify(allowed=True, reason=reason, command=command, output=simulate(conn, dev, command))
