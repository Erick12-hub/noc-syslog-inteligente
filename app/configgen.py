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
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from .auth import actor
from .config import Config
from .db import audit, get_db
from .interfaces import normalize_for_vendor, validate_interface_name

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
        # Fase 7.3: el equipo debe existir y su marca debe coincidir con la pedida.
        # Antes, un id inexistente se ignoraba y se generaba una configuración "genérica".
        if device is None:
            return jsonify(errors=["El equipo seleccionado no existe en el inventario"]), 400
        if device["vendor"] != v["vendor"]:
            return jsonify(errors=[f"El equipo {device['name']} es {device['vendor']}: no se le puede "
                                   f"generar una configuración {v['vendor']}"]), 400
    text = GENERATORS[v["vendor"]](v, device)
    audit(get_db(), actor(), "config.generate", "devices",
          device["id"] if device else None, f"{v['vendor']} servidor={v['server_ip']}:{v['port']} sev={v['severity']}")
    return jsonify(vendor=v["vendor"], config=text)


# ===========================================================================
# Fase 9.2: CONFIGURACIÓN BASE DESDE CERO (laboratorio)
#
#   GET /api/config/baseline?role=router&mode=prestamo&hostname=LAB-RTR01
#       &mgmt_ip=192.168.100.1&prefix=24&noc_ip=192.168.100.10&port=5514
#       &severity=6&device_id=8
#
# Los equipos del laboratorio son PRESTADOS: cualquiera los usa y se
# configuran desde cero en cada sesión por el cable de consola. Por eso:
#   - modo "prestamo": SIN usuarios, SIN contraseñas, SIN llaves SSH y SIN
#     guardar (write memory). Si la sesión se corta, el siguiente estudiante
#     no queda bloqueado y al reiniciar el equipo no queda nada nuestro.
#   - modo "fijo": agrega SSH v2 con usuario local; la credencial NO la
#     escribe el NOC: el bloque trae marcadores <USUARIO>/<CONTRASEÑA> que se
#     reemplazan a mano, y la misma credencial va SOLO en el .env del NOC.
# El resultado se divide en bloques: cuáles se escriben a mano, cuál se
# pega y cuáles se usan para verificar y para dejar el equipo limpio.
# ===========================================================================
ROLES = {
    # rol: (equipo de referencia, plataforma, interfaz de gestión, origen del Syslog)
    "router": ("Cisco Catalyst 8200L-1N-4T (IOS XE)", "cisco_xe", "GigabitEthernet0/0/0", "GigabitEthernet0/0/0"),
    "switch": ("Cisco Catalyst 2960-24TT-L (IOS)", "cisco_ios", "Vlan1", "Vlan1"),
}
BASELINE_MODES = ("prestamo", "fijo")
RE_HOSTNAME = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,62}$")   # regla de IOS: letra, letras/números/guion
# Palabras que NUNCA deben aparecer en una configuración de préstamo
CREDENTIAL_WORDS = ("username", "password", "secret", "crypto key", "write memory")


def _local_now():
    return datetime.now(timezone.utc) + timedelta(hours=Config.LOCAL_UTC_OFFSET)


def parse_mask(value) -> int:
    """'24', '/24' o '255.255.255.0' -> 24. Rango permitido: /8 a /30."""
    text = str(value or "").strip().lstrip("/")
    if "." in text:
        prefix = ipaddress.IPv4Network(f"0.0.0.0/{text}").prefixlen   # rechaza máscaras no contiguas
    else:
        prefix = int(text)
    if not 8 <= prefix <= 30:
        raise ValueError
    return prefix


def _validate_baseline(args) -> tuple[dict, list]:
    errors, v = [], {}
    v["role"] = args.get("role", "")
    if v["role"] not in ROLES:
        errors.append("Rol inválido. Opciones: router, switch")
    v["mode"] = args.get("mode", "prestamo")
    if v["mode"] not in BASELINE_MODES:
        errors.append("Modo inválido. Opciones: prestamo, fijo")
    v["hostname"] = args.get("hostname", "").strip()
    if not RE_HOSTNAME.match(v["hostname"]):
        errors.append("Hostname inválido: debe empezar con letra y llevar solo letras, números y guion (máx. 63)")
    prefix_ok = True
    try:
        v["prefix"] = parse_mask(args.get("prefix", "24"))
    except ValueError:
        errors.append("Máscara inválida: use prefijo (24) o máscara (255.255.255.0), entre /8 y /30")
        v["prefix"], prefix_ok = 24, False
    # Interfaz de gestión: la sugerida por rol o la que tenga el equipo real
    role_default = ROLES.get(v["role"], (None, None, ""))[2]
    raw_if = args.get("mgmt_if", "").strip() or role_default
    v["mgmt_if"] = normalize_for_vendor("Cisco", raw_if) if raw_if else ""
    if v["role"] in ROLES:
        if validate_interface_name("Cisco", v["mgmt_if"]):
            errors.append(f"Interfaz de gestión inválida: {raw_if!r} (ej. GigabitEthernet0/0/1, Vlan1)")
        elif v["role"] == "switch" and not v["mgmt_if"].startswith("Vlan"):
            errors.append("En el switch la gestión va en una interfaz Vlan (ej. Vlan1)")
        elif v["role"] == "router" and v["mgmt_if"].startswith("Vlan"):
            errors.append("En el router la gestión va en una interfaz física (ej. GigabitEthernet0/0/0)")
    ips = {}
    for field, label in (("mgmt_ip", "IP de gestión del equipo"), ("noc_ip", "IP del PC del NOC")):
        try:
            ips[field] = ipaddress.ip_address(args.get(field, "").strip())
            if ips[field].version != 4:
                raise ValueError
            v[field] = str(ips[field])
        except ValueError:
            errors.append(f"{label} inválida (IPv4)")
    gw = args.get("gateway", "").strip()
    v["gateway"], gw_ok = None, True
    if gw:
        try:
            v["gateway"] = str(ipaddress.IPv4Address(gw))
        except ValueError:
            errors.append("Puerta de enlace inválida")
            gw_ok = False
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
    # Coherencia de la red: el equipo, el PC y la puerta de enlace en la MISMA subred.
    # Se revisa siempre que las direcciones sean válidas, para mostrar TODOS los errores juntos.
    if len(ips) == 2 and prefix_ok and gw_ok:
        net = ipaddress.ip_interface(f"{v['mgmt_ip']}/{v['prefix']}").network
        v["netmask"] = str(net.netmask)
        v["network"] = str(net)
        if v["mgmt_ip"] == v["noc_ip"]:
            errors.append("La IP del equipo y la del PC del NOC no pueden ser iguales")
        if ips["noc_ip"] not in net:
            errors.append(f"El PC del NOC ({v['noc_ip']}) no está en la red del equipo ({net})")
        if v["gateway"] and ipaddress.ip_address(v["gateway"]) not in net:
            errors.append(f"La puerta de enlace no está en la red {net}")
        if ips["mgmt_ip"] in (net.network_address, net.broadcast_address):
            errors.append("La IP del equipo no puede ser la dirección de red ni la de broadcast")
    if v["role"] == "switch" and not gw:
        errors.append("El switch necesita la puerta de enlace (la IP del router)")
    return v, errors


def baseline(v: dict, device=None) -> list[dict]:
    """Devuelve los bloques de la configuración base: [{title, kind, text}]."""
    ref, platform, _default_if, _ = ROLES[v["role"]]
    mgmt_if = src_if = v["mgmt_if"]          # gestión y origen del Syslog: la misma interfaz
    lvl = CISCO_LEVELS[v["severity"]]
    is_router = v["role"] == "router"
    now = _local_now()
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    blocks = []

    # --- 0. Desde cero (a mano, en modo privilegiado) -------------------------
    clean = ["! Escriba estos comandos A MANO en PuTTY (no los pegue)",
             "enable",
             "write erase",
             "! Confirme con Enter."]
    if not is_router:
        clean += ["delete flash:vlan.dat",
                  "! Confirme dos veces con Enter (si dice que no existe, siga)."]
    clean += ["reload",
              "! 'System configuration has been modified. Save?' -> no",
              "! 'Proceed with reload?' -> Enter",
              "! Al arrancar: 'Would you like to enter the initial configuration dialog?' -> no",
              "! 'Would you like to terminate autoinstall?' -> yes (si aparece)"]
    blocks.append({"title": "0. Dejar el equipo de fábrica (a mano)", "kind": "manual", "text": "\n".join(clean)})

    # --- 1. Zona y hora (solo el router: es el servidor NTP del laboratorio) ---
    # Hallazgo de la sesión 1 (21-oct): con "clock set" ANTES de "clock timezone"
    # el router tomó la hora escrita como UTC y quedó 5 h atrás. Primero la zona.
    if is_router:
        blocks.append({"title": "1. Zona horaria y hora (a mano, antes de pegar)", "kind": "manual",
                       "text": "\n".join([
            "! El laboratorio no tiene Internet: el router será el servidor NTP.",
            "! PRIMERO la zona horaria y DESPUÉS la hora (si no, queda 5 h atrás).",
            "enable",
            "configure terminal",
            "clock timezone COT -5 0",
            "end",
            "! Escriba la hora REAL de Colombia en este momento:",
            f"clock set {now:%H:%M:%S} {now.day} {months[now.month - 1]} {now.year}",
            "show clock",
        ])})

    # --- 2. Bloque para pegar, EN TROZOS -----------------------------------------
    # Hallazgo de la sesión 1: pegar todo el bloque por consola (9600 baudios)
    # pierde líneas. Cada trozo es independiente (configure terminal ... end) y
    # tiene 5 líneas o menos: se pega uno, se espera el prompt y se pega el otro.
    chunks = [("Nombre del equipo", [f"hostname {v['hostname']}",
                                     "no ip domain lookup"])]   # IOS XE 17: con espacio
    if not is_router:
        vlan = int(mgmt_if[4:])
        if vlan != 1:          # la VLAN de gestión debe existir ANTES de su interfaz
            chunks.append(("VLAN de gestión", [f"vlan {vlan}", " name GESTION-NOC", " exit"]))
    chunks.append(("IP de gestión", [f"interface {mgmt_if}",
                                     f" description Gestion NOC lab ({v['network']})",
                                     f" ip address {v['mgmt_ip']} {v['netmask']}",
                                     " no shutdown"]))
    if not is_router:
        ports = ["interface range FastEthernet0/1 - 2",
                 " description Router / PC del NOC",
                 " switchport mode access"]
        if vlan != 1:
            ports.append(f" switchport access vlan {vlan}")
        ports.append(" no shutdown")
        chunks.append(("Puerta de enlace", [f"ip default-gateway {v['gateway']}"]))
        chunks.append(("Puertos hacia el router y el PC", ports))
    chunks.append(("Hora: zona y NTP", ["clock timezone COT -5 0",
                                        "ntp master 3" if is_router else f"ntp server {v['gateway']}"]))
    chunks.append(("Marcas de tiempo precisas", [
        "service timestamps log datetime msec localtime show-timezone year",
        "service timestamps debug datetime msec localtime show-timezone year",
        "service sequence-numbers"]))
    chunks.append(("Syslog hacia el NOC", [f"logging host {v['noc_ip']} transport udp port {v['port']}",
                                           f"logging trap {lvl}",
                                           "logging facility local7"]))
    chunks.append(("Origen y búfer del Syslog", [f"logging source-interface {src_if}",
                                                 f"logging buffered 16384 {lvl}"]))
    chunks.append(("Registro de cambios de configuración", [
        "archive", " log config", "  logging enable", "  notify syslog contenttype plaintext"]))
    chunks.append(("Registro de accesos", ["login on-failure log", "login on-success log"]))
    chunks.append(("Consola", ["line console 0", " logging synchronous", " exec-timeout 30 0"]))
    parts = [{"title": f"Trozo {i}: {title}",
              "text": "\n".join(["configure terminal", *body, "end"])}
             for i, (title, body) in enumerate(chunks, 1)]

    header = [
        "! ======================================================================",
        f"! NOC Syslog Inteligente - Configuración base {v['role'].upper()} ({v['mode'].upper()})",
        f"! Equipo de referencia: {ref}",
        f"! Generada: {now:%Y-%m-%d %H:%M} (hora de Colombia)",
        f"! Gestión: {mgmt_if} {v['mgmt_ip']}/{v['prefix']} -> NOC {v['noc_ip']} UDP {v['port']}",
    ]
    if v["mode"] == "prestamo":
        header += ["! EQUIPO PRESTADO: sin usuarios, sin contraseñas y sin guardar.",
                   "! Al reiniciarlo no queda nada de esta configuración."]
    header += [
        "! Pegue UN trozo a la vez y espere el prompt antes del siguiente:",
        "! pegar todo junto por consola pierde líneas (hallazgo del laboratorio).",
        "! Si una línea responde '% Invalid input', anótela y siga con el próximo.",
        "! ======================================================================",
    ]
    footer = ["write memory"] if v["mode"] == "fijo" else \
        ["! (préstamo: la configuración NO se guarda en la memoria del equipo)"]
    if v["mode"] == "fijo":
        parts.append({"title": f"Trozo {len(parts) + 1}: Guardar", "text": "write memory"})
    text = "\n".join(header + [f"! --- {p['title']} ---\n{p['text']}" for p in parts] + footer)
    blocks.append({"title": "2. Configuración base (pegar en PuTTY, un trozo a la vez)", "kind": "pegar",
                   "text": text, "chunks": parts})

    # --- 2b. SSH para equipos FIJOS (editar antes de pegar) --------------------
    if v["mode"] == "fijo":
        blocks.append({"title": "2b. SSH para equipo fijo (reemplace los marcadores ANTES de pegar)",
                       "kind": "manual", "text": "\n".join([
            "! Reemplace <USUARIO> y <CONTRASEÑA>. La MISMA credencial va SOLO en el .env",
            "! del NOC (SSH_USERNAME / SSH_PASSWORD). Nunca en GitHub ni en capturas.",
            "configure terminal",
            "ip domain-name noc.lab",
            "crypto key generate rsa modulus 2048",
            "ip ssh version 2",
            "ip ssh time-out 60",
            "ip ssh authentication-retries 3",
            "username <USUARIO> privilege 15 algorithm-type scrypt secret <CONTRASEÑA>",
            "line vty 0 4",
            " login local",
            " transport input ssh",
            " exec-timeout 15 0",
            " exit",
            "end",
            "write memory",
        ])})

    # --- 3. Verificación --------------------------------------------------------
    verify = [
        "! Ejecute cada uno y revise lo indicado:",
        "show version | include uptime|Version|board|operating mode",
        "!   -> modelo y número de serie (el NOC los leerá igual al conectarse)",
        "show ip interface brief",
        f"!   -> {mgmt_if} con {v['mgmt_ip']} 'up / up'",
        f"ping {v['noc_ip']}",
        "!   -> !!!!! (si falla: cable, IP del PC o firewall de Windows)",
        "show clock",
        "!   -> hora correcta y zona COT" + ("" if is_router else
                                           " (el 2960 arranca en 1993 hasta que sincroniza)"),
        "show ntp associations" if is_router else "show ntp status",
        "!   -> " + ("127.127.1.1 como referencia (es el servidor)" if is_router
                    else f"'Clock is synchronized' con {v['gateway']} (puede tardar 5-15 min)"),
        "show logging | include Logging to|Trap",
        f"!   -> 'Logging to {v['noc_ip']} (udp port {v['port']}...)'",
        f'send log 6 "Prueba NOC desde {v["hostname"]}"',
        "!   -> el mensaje debe aparecer en la página Eventos del NOC",
    ]
    blocks.append({"title": "3. Verificación (por consola)", "kind": "verificar", "text": "\n".join(verify)})

    # --- 4. Al terminar la sesión ------------------------------------------------
    end = ["! Antes de devolver el equipo (a mano):", "enable", "write erase"]
    if not is_router:
        end += ["delete flash:vlan.dat"]
    end += ["reload", "! 'Save?' -> no   ·   el equipo queda de fábrica para el siguiente estudiante"]
    blocks.append({"title": "4. Al terminar: dejar el equipo limpio", "kind": "manual", "text": "\n".join(end)})
    return blocks


@bp.get("/baseline")
def baseline_endpoint():
    v, errors = _validate_baseline(request.args)
    device = None
    if request.args.get("device_id"):
        device = get_db().execute("SELECT * FROM devices WHERE id = ?", (request.args["device_id"],)).fetchone()
        if device is None:
            errors.append("El equipo seleccionado no existe en el inventario")
        elif device["vendor"] != "Cisco":
            errors.append(f"La configuración base es para Cisco; {device['name']} es {device['vendor']}")
        elif v.get("mgmt_ip") and device["ip"] != v["mgmt_ip"]:
            errors.append(f"La IP de gestión ({v['mgmt_ip']}) no coincide con la del inventario "
                          f"para {device['name']} ({device['ip']}): el NOC rechazaría su Syslog")
    if errors:
        return jsonify(errors=errors), 400
    blocks = baseline(v, device)
    audit(get_db(), actor(), "config.baseline", "devices", device["id"] if device else None,
          f"{v['role']} {v['mode']} {v['hostname']} {v['mgmt_if']} {v['mgmt_ip']}/{v['prefix']} "
          f"-> NOC {v['noc_ip']}:{v['port']}")
    return jsonify(role=v["role"], mode=v["mode"], platform=ROLES[v["role"]][1], blocks=blocks)
