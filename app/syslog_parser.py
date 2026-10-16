"""
Parser de mensajes Syslog (RFC 3164, RFC 5424 y formatos de fabricante).

Recibe el texto CRUDO de un mensaje y devuelve un diccionario con sus partes:
facility, severidad, fecha, equipo, aplicación, mensaje y fabricante detectado.

IMPORTANTE (seguridad): este módulo solo LEE y CLASIFICA texto. Nunca ejecuta
ni interpreta el contenido del mensaje como una orden. El mensaje es un dato
no confiable que puede venir de cualquiera.

Estructura de un mensaje Syslog:

    <PRI>  CABECERA                    MENSAJE
    <187>  Oct  5 18:00:00 RTR01       %LINK-3-UPDOWN: Interface Gi0/1, changed state to down

    PRI = facility * 8 + severidad      ->  187 = 23 * 8 + 3
    facility  = PRI // 8  (división entera)  -> 23 = local7
    severidad = PRI %  8  (resto)            ->  3 = Error
"""
import re

# ---------------------------------------------------------------------------
# Catálogos (RFC 5424, sección 6.2.1)
# ---------------------------------------------------------------------------
FACILITIES = [
    "kern", "user", "mail", "daemon", "auth", "syslog", "lpr", "news",
    "uucp", "cron", "authpriv", "ftp", "ntp", "security", "console", "clock",
    "local0", "local1", "local2", "local3", "local4", "local5", "local6", "local7",
]
SEVERITY_NAMES = [
    "Emergency", "Alert", "Critical", "Error",
    "Warning", "Notice", "Informational", "Debug",
]

# Fortinet escribe la severidad como palabra en el campo level=
FORTINET_LEVELS = {
    "emergency": 0, "alert": 1, "critical": 2, "error": 3,
    "warning": 4, "notice": 5, "information": 6, "debug": 7,
}

MAX_MESSAGE_LEN = 2000  # límite de longitud: evita mensajes gigantes en la BD

# ---------------------------------------------------------------------------
# Expresiones regulares
# ---------------------------------------------------------------------------
# <PRI> al inicio: 1 a 3 dígitos entre < >
RE_PRI = re.compile(r"^<(\d{1,3})>(.*)$", re.S)

# RFC 5424:  1 TIMESTAMP HOSTNAME APP-NAME PROCID MSGID [SD] MSG
RE_5424 = re.compile(
    r"^1 (?P<ts>\S+) (?P<host>\S+) (?P<app>\S+) (?P<proc>\S+) (?P<msgid>\S+) "
    r"(?P<sd>-|(?:\[.*?\])+)\s?(?P<msg>.*)$", re.S)

# RFC 3164:  [seq: ][*]Mmm dd [yyyy] hh:mm:ss[.ms] [TZ][:] RESTO
#   - Cisco antepone un número de secuencia ("45: ") y a veces "*"
#   - Huawei incluye el año ("Oct 5 2026 18:00:00")
RE_3164_TS = re.compile(
    r"^(?:\d+:\s*)?\*?(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}(?:\s+\d{4})?\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
    r"(?:\s+[A-Z]{3,4})?:?\s+(?P<rest>.*)$", re.S)

# Cisco IOS:  %FACILITY-SEVERIDAD-MNEMONICO: texto      ej. %LINK-3-UPDOWN:
RE_CISCO = re.compile(r"%(?P<fac>[A-Z][A-Z0-9_]*)-(?P<sev>[0-7])-(?P<mn>[A-Z0-9_]+)\s*:\s*(?P<msg>.*)", re.S)

# Huawei VRP:  %%01MODULO/SEVERIDAD/NOMBRE(tipo)[n]: texto   ej. %%01SHELL/5/CMDRECORD(s):
RE_HUAWEI = re.compile(
    r"%%\d{2}(?P<mod>[A-Z0-9_]+)/(?P<sev>[0-7])/(?P<mn>[A-Z0-9_]+)(?:\([a-z]\))?(?:\[\d+\])?:\s*(?P<msg>.*)", re.S)

# Fortinet FortiOS: pares clave=valor, siempre trae logid=
RE_FORTI_DETECT = re.compile(r'\blogid="?\d+')
RE_KV = re.compile(r'(\w+)=("([^"]*)"|\S+)')

# TAG de aplicación RFC 3164: palabra seguida opcionalmente de [pid] y ":"
RE_TAG = re.compile(r"^(?P<tag>[A-Za-z][\w.\-/]{0,47})(?:\[\d+\])?:\s")

# Caracteres de control (incluye saltos de línea; se conserva solo el tabulador). Se eliminan para que un mensaje no
# pueda "romper" la pantalla o falsificar líneas de log (log injection).
RE_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")


def sanitize(text: str) -> tuple[str, bool]:
    """Quita caracteres de control y recorta. Devuelve (texto, fue_recortado)."""
    clean = RE_CONTROL.sub(" ", text).strip()
    if len(clean) > MAX_MESSAGE_LEN:
        return clean[:MAX_MESSAGE_LEN] + " [...]", True
    return clean, False


def _detect_vendor(result: dict, text: str):
    """Busca la firma de Cisco, Huawei o Fortinet dentro del texto."""
    m = RE_HUAWEI.search(text)  # se revisa antes que Cisco: "%%" también contiene "%"
    if m:
        result.update(vendor_hint="Huawei", vendor_severity=int(m["sev"]),
                      mnemonic=f'{m["mod"]}/{m["sev"]}/{m["mn"]}', message=m["msg"])
        return
    m = RE_CISCO.search(text)
    if m:
        result.update(vendor_hint="Cisco", vendor_severity=int(m["sev"]),
                      mnemonic=f'{m["fac"]}-{m["sev"]}-{m["mn"]}', message=m["msg"])
        return
    if RE_FORTI_DETECT.search(text):
        kv = {k: (quoted if quoted is not None and val.startswith('"') else val)
              for k, val, quoted in RE_KV.findall(text)}
        level = kv.get("level", "").lower()
        result.update(
            vendor_hint="Fortinet",
            vendor_severity=FORTINET_LEVELS.get(level),
            mnemonic=f'logid={kv.get("logid")}',
            hostname=kv.get("devname") or result.get("hostname"),
            app_name="/".join(x for x in (kv.get("type"), kv.get("subtype")) if x) or result.get("app_name"),
            message=kv.get("msg") or kv.get("logdesc") or text,
        )
        if kv.get("date") and kv.get("time"):
            result["event_time"] = f'{kv["date"]} {kv["time"]}'


# ---------------------------------------------------------------------------
# Fase 7: interfaz y puertos involucrados en el evento
# ---------------------------------------------------------------------------
# Nombres LARGOS de interfaz (Cisco y Huawei). El número admite ranuras
# (0/0/1) y subinterfaces (.100).   ej. GigabitEthernet0/0/2, Vlanif10, Eth-Trunk1
RE_IFACE_LONG = re.compile(
    r"\b(?P<name>(?:Ten|Twenty[Ff]ive|Forty|Hundred)?GigabitEthernet|XGigabitEthernet|"
    r"FastEthernet|Ethernet|Serial|Vlanif|Vlan|Loopback|Port-channel|Eth-Trunk|Tunnel|MEth|NULL)"
    r"\s?(?P<num>\d+(?:/\d+)*(?:\.\d+)?)\b")

# Nombres CORTOS de Cisco/Huawei, solo después de la palabra "Interface"
# para no confundirlos con otras palabras.   ej. "Interface Gi0/1", "interface GE0/0/1"
RE_IFACE_SHORT = re.compile(
    r"\b[Ii]nterface\s+(?P<abbr>Gi|Fa|Te|Et|Se|Po|Lo|Tu|Vl|GE|XGE|Eth)(?P<num>\d+(?:/\d+)*(?:\.\d+)?)\b")

# Interfaz de FortiGate en texto libre:  "Interface wan1 bandwidth ..."
RE_IFACE_FORTI_TEXT = re.compile(r'\b[Ii]nterface\s+"?(?P<name>[A-Za-z][\w.\-]{0,14})"?')

# Abreviatura -> nombre largo (para guardar siempre el mismo nombre y luego
# poder compararlo con la lista de interfaces reales del equipo, Fase 8/9).
IFACE_ABBR = {
    "Gi": "GigabitEthernet", "Fa": "FastEthernet", "Te": "TenGigabitEthernet",
    "Et": "Ethernet", "Se": "Serial", "Po": "Port-channel", "Lo": "Loopback",
    "Tu": "Tunnel", "Vl": "Vlan", "GE": "GigabitEthernet", "XGE": "XGigabitEthernet",
    "Eth": "Eth-Trunk",
}

# ACL de Cisco:  "denied tcp 203.0.113.200(51515) -> 192.0.2.1(22)"
RE_ACL_PORTS = re.compile(
    r"(?P<src>\d{1,3}(?:\.\d{1,3}){3})\((?P<sport>\d+)\)\s*->\s*"
    r"(?P<dst>\d{1,3}(?:\.\d{1,3}){3})\((?P<dport>\d+)\)")
# Login de Cisco:  "[Source: 203.0.113.200] [localport: 22]"  -> puerto atacado
RE_LOCALPORT = re.compile(r"\[localport:\s*(?P<port>\d+)\]")
# Estilo sshd/Linux:  "from 203.0.113.200 port 51515"  -> puerto de origen
RE_FROM_PORT = re.compile(r"\bfrom\s+\d{1,3}(?:\.\d{1,3}){3}\s+port\s+(?P<port>\d+)")

# Sintaxis permitida de una interfaz (sirve también para validar filtros):
# empieza con letra; luego letras, números, / . - _ :   (máx. 48 caracteres)
RE_IFACE_VALID = re.compile(r"^[A-Za-z][A-Za-z0-9_./:\-]{0,47}$")


def is_valid_port(value) -> bool:
    """Un puerto TCP/UDP válido es un entero entre 1 y 65535."""
    try:
        return 1 <= int(value) <= 65535
    except (TypeError, ValueError):
        return False


def is_valid_interface(name) -> bool:
    """Valida solo la SINTAXIS del nombre (si existe en el equipo se valida en la Fase 9)."""
    return isinstance(name, str) and bool(RE_IFACE_VALID.match(name))


def normalize_interface(name: str) -> str:
    """'Gi0/1' -> 'GigabitEthernet0/1'. Si no es una abreviatura conocida, se deja igual."""
    m = re.match(r"^(?P<abbr>[A-Za-z\-]+?)(?P<num>\d.*)$", name or "")
    if m and m["abbr"] in IFACE_ABBR:
        return IFACE_ABBR[m["abbr"]] + m["num"]
    return name


def extract_network(text: str, vendor_hint: str | None) -> dict:
    """
    Busca en el mensaje la interfaz y los puertos involucrados.

    Devuelve {"interface", "src_port", "dst_port", "flags"}. Un valor que no
    se encuentra queda en None. Un puerto fuera de 1-65535 NO se guarda y se
    marca con 'puerto_invalido' (el mensaje pudo ser alterado).
    """
    out = {"interface": None, "src_port": None, "dst_port": None, "flags": []}
    sport = dport = None

    if vendor_hint == "Fortinet":
        # FortiOS trae los datos como clave=valor: srcintf, srcport, dstport
        kv = {k: (q if v.startswith('"') else v) for k, v, q in RE_KV.findall(text)}
        out["interface"] = kv.get("srcintf") or kv.get("intf") or kv.get("interface")
        sport, dport = kv.get("srcport"), kv.get("dstport")
        if not out["interface"]:
            m = RE_IFACE_FORTI_TEXT.search(kv.get("msg") or "")
            if m:
                out["interface"] = m["name"]
    else:
        m = RE_IFACE_LONG.search(text)
        if m:
            out["interface"] = m["name"] + m["num"]
        else:
            m = RE_IFACE_SHORT.search(text)
            if m:
                out["interface"] = IFACE_ABBR[m["abbr"]] + m["num"]

        m = RE_ACL_PORTS.search(text)
        if m:
            sport, dport = m["sport"], m["dport"]
        else:
            m = RE_LOCALPORT.search(text)
            if m:
                dport = m["port"]
            m = RE_FROM_PORT.search(text)
            if m:
                sport = m["port"]

    # Validación: solo se guardan puertos dentro del rango permitido
    for key, val in (("src_port", sport), ("dst_port", dport)):
        if val is None:
            continue
        if is_valid_port(val):
            out[key] = int(val)
        elif "puerto_invalido" not in out["flags"]:
            out["flags"].append("puerto_invalido")

    # Una interfaz con caracteres extraños se descarta (dato no confiable)
    if out["interface"] and not is_valid_interface(out["interface"]):
        out["interface"] = None
        out["flags"].append("interfaz_invalida")
    return out


def parse(raw: str) -> dict:
    """
    Analiza un mensaje Syslog crudo.

    Devuelve un diccionario con: pri, facility, facility_name, severity,
    severity_name, format, event_time, hostname, app_name, message, mnemonic,
    vendor_hint, vendor_severity, interface, src_port, dst_port y
    parse_flags (lista de observaciones).
    """
    text = raw.strip("\r\n\x00 ")
    result = {
        "pri": None, "facility": None, "severity": None, "format": "desconocido",
        "event_time": None, "hostname": None, "app_name": None, "message": text,
        "mnemonic": None, "vendor_hint": None, "vendor_severity": None,
        "interface": None, "src_port": None, "dst_port": None,
        "parse_flags": [],
    }

    # 1) PRI -> facility y severidad
    m = RE_PRI.match(text)
    rest = text
    if m and int(m.group(1)) <= 191:          # 191 = 23*8+7, el máximo válido
        pri = int(m.group(1))
        result.update(pri=pri, facility=pri // 8, severity=pri % 8)
        rest = m.group(2)
    else:
        result["parse_flags"].append("sin_pri")

    # 2) Cabecera: RFC 5424, RFC 3164 o ninguna
    m5424 = RE_5424.match(rest)
    m3164 = RE_3164_TS.match(rest)
    if m5424:
        result["format"] = "rfc5424"
        nil = lambda v: None if v == "-" else v   # en 5424 "-" significa vacío
        result.update(event_time=nil(m5424["ts"]), hostname=nil(m5424["host"]),
                      app_name=nil(m5424["app"]), message=m5424["msg"])
    elif m3164:
        result["format"] = "rfc3164"
        result["event_time"] = re.sub(r"\s+", " ", m3164["ts"])
        body = m3164["rest"]
        # Si la primera palabra no es una firma de fabricante ni clave=valor,
        # es el nombre del equipo (HOSTNAME).
        first, _, remainder = body.partition(" ")
        if remainder and not first.startswith("%") and "=" not in first:
            result["hostname"] = first.rstrip(":")
            body = remainder
        # TAG de la aplicación al estilo RFC 3164: "sshd[123]: texto"
        mtag = RE_TAG.match(body)
        if mtag:
            result["app_name"] = mtag["tag"]
        result["message"] = body
    elif result["pri"] is not None:
        result["format"] = "solo_pri"
        result["message"] = rest

    # 3) Firma del fabricante (Cisco / Huawei / Fortinet)
    _detect_vendor(result, rest)
    if result["vendor_hint"] == "Fortinet" and result["format"] in ("solo_pri", "desconocido"):
        result["format"] = "clave_valor"
    if result["vendor_hint"] in ("Cisco", "Huawei"):
        result["app_name"] = result["app_name"] or result["mnemonic"].split("-")[0].split("/")[0]

    # Integridad: la severidad del PRI y la del fabricante deberían coincidir.
    # Si no coinciden, el mensaje pudo ser alterado o el equipo está mal configurado.
    if (result["pri"] is not None and result["vendor_severity"] is not None
            and result["vendor_severity"] != result["severity"]):
        result["parse_flags"].append("severidad_inconsistente")

    # 4) Severidad final: manda el PRI; si no hay PRI se usa la del fabricante;
    #    si tampoco existe, se asume 6 (Informational).
    if result["severity"] is None:
        if result["vendor_severity"] is not None:
            result["severity"] = result["vendor_severity"]
        else:
            result["severity"] = 6
            result["parse_flags"].append("severidad_asumida")
    if result["facility"] is None:
        result["facility"] = 1  # "user", valor por defecto de la RFC 3164

    # 5) Fase 7: interfaz y puertos (se buscan en el texto completo)
    net = extract_network(rest, result["vendor_hint"])
    result.update(interface=net["interface"], src_port=net["src_port"], dst_port=net["dst_port"])
    result["parse_flags"] += net["flags"]

    # 6) Limpieza del mensaje (caracteres de control y longitud)
    result["message"], truncated = sanitize(result["message"] or "")
    if truncated:
        result["parse_flags"].append("mensaje_recortado")
    if not result["message"]:
        result["message"] = "(mensaje vacío)"

    result["facility_name"] = FACILITIES[result["facility"]]
    result["severity_name"] = SEVERITY_NAMES[result["severity"]]
    return result
