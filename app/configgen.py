"""
Generador de configuraciones Syslog comentadas para Cisco, Fortinet y Huawei (RF-09).

    GET /api/config/generate?vendor=Cisco&server_ip=192.0.2.250&port=5514
        &severity=6&ntp=192.0.2.123&source=GigabitEthernet0/0/0&device_id=1

Cada plantilla aplica la MISMA política en la sintaxis de cada fabricante:
  1. Hora sincronizada por NTP (sin hora correcta no se pueden correlacionar eventos).
  2. Marca de tiempo precisa en cada mensaje.
  3. Servidor Syslog del NOC y puerto.
  4. Severidad mínima que se envía.
  5. Interfaz/IP de origen fija: debe coincidir con la IP registrada en el
     inventario del NOC (lista permitida de fuentes).
  6. Registro de cambios de configuración y de inicios de sesión.
  7. Comandos de verificación.

SEGURIDAD: todos los parámetros se validan antes de insertarlos en la plantilla.
Un nombre de interfaz como "Gi0/0\\nreload" se rechaza: así nadie puede usar el
generador para "colar" comandos en la configuración que se copiará al equipo.
Las plantillas son para LABORATORIO: revise la sintaxis según la versión del
equipo y aplíquelas solo en equipos autorizados.
"""
import ipaddress
import re

from flask import Blueprint, current_app, jsonify, request

from .db import audit, get_db

bp = Blueprint("configgen", __name__, url_prefix="/api/config")

# Palabra clave de cada severidad (0-7) en cada sistema operativo
CISCO_LEVELS = ["emergencies", "alerts", "critical", "errors",
                "warnings", "notifications", "informational", "debugging"]
FORTI_LEVELS = ["emergency", "alert", "critical", "error",
                "warning", "notification", "information", "debug"]
HUAWEI_LEVELS = ["emergencies", "alert", "critical", "error",
                 "warning", "notification", "informational", "debugging"]
SEV_NAMES = ["Emergency", "Alert", "Critical", "Error", "Warning", "Notice", "Informational", "Debug"]

# Interfaz: letras, números, "/", ".", "-" y ":" (Gi0/0/0, Vlanif10, wan1, port1)
RE_IFACE = re.compile(r"^[A-Za-z][A-Za-z0-9/.:\-]{0,39}$")


def _validate(args) -> tuple[dict, list]:
    errors, v = [], {}
    v["vendor"] = args.get("vendor", "")
    if v["vendor"] not in ("Cisco", "Fortinet", "Huawei"):
        errors.append("Marca inválida. Opciones: Cisco, Fortinet, Huawei")
    for field, label in (("server_ip", "IP del servidor Syslog"), ("ntp", "IP del servidor NTP")):
        try:
            v[field] = str(ipaddress.ip_address(args.get(field, "").strip()))
        except ValueError:
            errors.append(f"{label} inválida")
    try:
        v["port"] = int(args.get("port", "5514"))
        if not 1 <= v["port"] <= 65535:
            raise ValueError
    except ValueError:
        errors.append("Puerto inválido (1-65535)")
    try:
        v["severity"] = int(args.get("severity", "6"))
        if not 0 <= v["severity"] <= 7:
            raise ValueError
    except ValueError:
        errors.append("Severidad inválida (0-7)")
    v["source"] = args.get("source", "").strip()
    if not RE_IFACE.match(v["source"]):
        errors.append("Interfaz de origen inválida (ej. GigabitEthernet0/0/0, wan1, Vlanif10)")
    return v, errors


def _header(v, device, comment):
    c = comment
    lines = [
        f"{c} ======================================================================",
        f"{c} NOC Syslog Inteligente - Configuración Syslog para {v['vendor']}",
        f"{c} Equipo destino : {device['name'] + ' (' + device['ip'] + ')' if device else '(no especificado)'}",
        f"{c} Servidor Syslog: {v['server_ip']} puerto UDP {v['port']}",
        f"{c} Severidad      : {v['severity']} ({SEV_NAMES[v['severity']]}) y más graves",
        f"{c} PLANTILLA DE LABORATORIO: verifique la sintaxis según la versión del",
        f"{c} equipo y aplíquela SOLO en equipos autorizados.",
    ]
    if device and device["is_simulated"]:
        lines.append(f"{c} EQUIPO SIMULADO: esta configuración es de ejemplo.")
    lines.append(f"{c} ======================================================================")
    return lines


def cisco(v, device):
    lvl = CISCO_LEVELS[v["severity"]]
    return "\n".join(_header(v, device, "!") + [
        "configure terminal",
        "!",
        "! --- 1. Hora sincronizada (NTP) -------------------------------------",
        "! Sin la hora correcta no se pueden ordenar ni correlacionar eventos.",
        f"ntp server {v['ntp']}",
        "clock timezone COT -5 0",
        "!",
        "! --- 2. Marca de tiempo precisa en cada mensaje ---------------------",
        "service timestamps log datetime msec localtime show-timezone",
        "service sequence-numbers",
        "!",
        "! --- 3. Servidor Syslog del NOC -------------------------------------",
        f"logging host {v['server_ip']} transport udp port {v['port']}",
        "logging facility local7",
        "!",
        f"! --- 4. Severidad mínima enviada: {v['severity']} ({SEV_NAMES[v['severity']]}) ---",
        f"logging trap {lvl}",
        "!",
        "! --- 5. Interfaz de origen fija -------------------------------------",
        "! Su IP debe estar registrada como fuente AUTORIZADA en el inventario del NOC.",
        f"logging source-interface {v['source']}",
        "!",
        "! --- 6. Registro de cambios de configuración y de accesos -----------",
        "archive",
        " log config",
        "  logging enable",
        "  notify syslog contenttype plaintext",
        "  hidekeys",
        " exit",
        "exit",
        "login on-failure log",
        "login on-success log",
        "!",
        "end",
        "write memory",
        "!",
        "! --- 7. Verificación ------------------------------------------------",
        "! show logging              -> debe listar el host y el nivel configurados",
        "! show ntp associations     -> el servidor NTP debe aparecer sincronizado (*)",
        "! show clock                -> hora y zona correctas",
        "! send log 6 \"Prueba NOC\"    -> el mensaje debe llegar al NOC",
    ])


def fortinet(v, device):
    lvl = FORTI_LEVELS[v["severity"]]
    return "\n".join(_header(v, device, "#") + [
        "# --- 1. Hora sincronizada (NTP) -------------------------------------",
        "config system ntp",
        "    set ntpsync enable",
        "    set type custom",
        "    config ntpserver",
        "        edit 1",
        f"            set server \"{v['ntp']}\"",
        "        next",
        "    end",
        "end",
        "",
        "# --- 2 y 3. Servidor Syslog del NOC ---------------------------------",
        "config log syslogd setting",
        "    set status enable",
        f"    set server \"{v['server_ip']}\"",
        "    set mode udp",
        f"    set port {v['port']}",
        "    set facility local7",
        "    set format default",
        "    # 5. Interfaz de origen fija (su IP debe estar AUTORIZADA en el NOC)",
        "    set interface-select-method specify",
        f"    set interface \"{v['source']}\"",
        "end",
        "",
        f"# --- 4. Severidad mínima enviada: {v['severity']} ({SEV_NAMES[v['severity']]}) ---",
        "config log syslogd filter",
        f"    set severity {lvl}",
        "    # 6. Incluir eventos del sistema (accesos y cambios de configuración)",
        "    set forward-traffic disable",
        "    set local-traffic disable",
        "end",
        "",
        "# --- 7. Verificación ------------------------------------------------",
        "# get log syslogd setting      -> estado enable, servidor y puerto",
        "# diagnose sys ntp status      -> sincronizado con el servidor NTP",
        "# diagnose log test            -> genera mensajes de prueba hacia el NOC",
    ])


def huawei(v, device):
    lvl = HUAWEI_LEVELS[v["severity"]]
    return "\n".join(_header(v, device, "#") + [
        "system-view",
        "#",
        "# --- 1. Hora sincronizada (NTP) -------------------------------------",
        f"ntp-service unicast-server {v['ntp']}",
        "clock timezone COT minus 05:00:00",
        "#",
        "# --- 2. Centro de información y marca de tiempo precisa -------------",
        "info-center enable",
        "info-center timestamp log date precision-time millisecond",
        "#",
        "# --- 3 y 5. Servidor Syslog del NOC e interfaz de origen fija -------",
        "# La IP de la interfaz de origen debe estar AUTORIZADA en el NOC.",
        f"info-center loghost source {v['source']}",
        f"info-center loghost {v['server_ip']} port {v['port']} facility local7",
        "#",
        f"# --- 4. Severidad mínima enviada: {v['severity']} ({SEV_NAMES[v['severity']]}) ---",
        f"info-center source default channel loghost log level {lvl}",
        "#",
        "# --- 6. Registro de comandos (quién ejecutó qué) --------------------",
        "# VRP registra cada comando con SHELL/5/CMDRECORD; se envía al NOC con el canal loghost.",
        "info-center source SHELL channel loghost log level notification",
        "#",
        "return",
        "save",
        "#",
        "# --- 7. Verificación ------------------------------------------------",
        "# display info-center          -> loghost, puerto y nivel configurados",
        "# display ntp-service status   -> clock status: synchronized",
        "# display clock                -> hora y zona correctas",
    ])


GENERATORS = {"Cisco": cisco, "Fortinet": fortinet, "Huawei": huawei}


@bp.get("/generate")
def generate():
    v, errors = _validate(request.args)
    if errors:
        return jsonify(errors=errors), 400
    device = None
    if request.args.get("device_id"):
        device = get_db().execute("SELECT * FROM devices WHERE id = ?",
                                  (request.args["device_id"],)).fetchone()
    text = GENERATORS[v["vendor"]](v, device)
    audit(get_db(), current_app.config["DEFAULT_OPERATOR"], "config.generate", "devices",
          device["id"] if device else None, f"{v['vendor']} servidor={v['server_ip']}:{v['port']} sev={v['severity']}")
    return jsonify(vendor=v["vendor"], config=text)
