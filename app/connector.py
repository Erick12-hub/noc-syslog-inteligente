"""
Fase 9.1: gestor de conexiones con los equipos, con TRAZABILIDAD.

    POST /api/devices/<id>/session   {"commands": ["show ip interface brief"]}
         Abre una sesión, IDENTIFICA el equipo físico, ejecuta los comandos
         permitidos y cierra. Sin comandos = solo identificar.
    GET  /api/devices/<id>/sessions  Historial de sesiones del equipo
    GET  /api/sessions/<sid>         Una sesión con sus comandos y salidas

MODOS DE CONEXIÓN (campo devices.connection_mode):
    ninguno   El NOC solo recibe Syslog del equipo; no se conecta.
    simulado  Respuestas de ejemplo (samples/cli/): equipos SIM- y pruebas.
    consola   Cable de consola (COM3). Para equipos PRESTADOS: sin contraseñas
              en el equipo. Netmiko solo lo soporta para Cisco.
    ssh       Equipos FIJOS. Usuario y contraseña SOLO en .env; la huella de
              la llave SSH del equipo se fija la primera vez y si cambia la
              sesión se aborta (posible suplantación del equipo).

El resto NO depende del modo: misma lista permitida de comandos (la de
app/console.py), mismos roles, misma auditoría encadenada y el mismo
registro de sesiones y comandos.

FLUJO DE UNA SESIÓN
    1. Validar TODOS los comandos con la política. Si alguno se bloquea, no se
       abre ninguna conexión (y el intento queda auditado).
    2. Reservar el equipo/puerto (un puerto COM solo atiende una sesión).
    3. Conectar y registrar la sesión ('abierta').
    4. Identificar: show version -> número de serie, modelo, versión, avisos.
       Si el número de serie cambió desde la última vez -> ALERTA (es otro
       equipo físico; con equipos prestados pasa).
    5. Ejecutar los comandos; guardar cada salida con su huella SHA-256.
    6. Cerrar la sesión ('cerrada' o 'fallida') y auditar.
"""
import base64
import hashlib
import re
import threading
import time

from flask import Blueprint, jsonify, request

from .auth import actor as session_actor
from .config import BASE_DIR, Config
from .console import check as check_command, simulate as console_simulate
from .db import audit, get_db, now_iso

bp = Blueprint("connector", __name__, url_prefix="/api")

MODES = ("ninguno", "simulado", "consola", "ssh")
# Plataformas de Netmiko permitidas por marca
PLATFORMS = {
    "Cisco": ("cisco_ios", "cisco_xe"),
    "Fortinet": ("fortinet",),
    "Huawei": ("huawei",),
    "Otro": (),
}
DEFAULT_PLATFORM = {"Cisco": "cisco_ios", "Fortinet": "fortinet", "Huawei": "huawei"}
# Comando que identifica al equipo (modelo, versión y número de serie)
IDENTITY_COMMAND = {"cisco_ios": "show version", "cisco_xe": "show version",
                    "fortinet": "get system status", "huawei": "display version"}
RE_CONSOLE_PORT = re.compile(r"^(COM\d{1,3}|/dev/tty[A-Za-z0-9]{1,12})$")
MAX_COMMANDS = 5
MAX_OUTPUT = 64 * 1024            # se guardan 64 KB por salida (la huella es de TODA la salida)
MAX_CAPTURE = 512 * 1024          # Fase 10.1: la configuración se guarda completa (hasta 512 KB)
SAMPLES_DIR = BASE_DIR / "samples" / "cli"


class ConnectionError_(Exception):
    """Error al conectar o al ejecutar (mensaje apto para mostrar: sin secretos)."""


# ---------------------------------------------------------------------------
# 1. TRANSPORTES: misma interfaz (open, send, close) para todos los modos
# ---------------------------------------------------------------------------
class SimulatedTransport:
    """Responde con las salidas de ejemplo de samples/cli/<plataforma>/. No hay red."""
    transport = "simulado"

    def __init__(self, device, conn):
        self.device, self.conn = device, conn
        self.target = "simulado"
        self.host_key_fp = None

    def open(self):
        pass

    def send(self, command: str) -> str:
        if command.startswith(("ping ", "traceroute ")):
            return simulated_diagnostic(command)
        sample = SAMPLES_DIR / (self.device["platform"] or "") / (command.replace(" ", "_") + ".txt")
        if sample.is_file():
            text = sample.read_text(encoding="utf-8")
            if command == "show running-config":
                text = simulated_running_config(text, self.device, self.conn)
                return apply_config_lines(text, simulated_applied(self.conn, self.device["id"]))
            return text
        return console_simulate(self.conn, self.device, command)   # salida simulada de la Fase 4

    def send_config(self, lines: list[str]) -> str:
        """Fase 10.3: "aplica" las líneas al equipo simulado (quedan guardadas en
        sim_device_config) y responde como lo haría IOS."""
        bad = [l for l in lines if l.strip().lower().startswith(("simular-error", "ip address 999."))]
        echo = [f"{self.device['name']}(config)#{l.strip()}" for l in lines]
        if bad:          # para probar el rollback: una línea que el equipo rechaza
            return "\n".join(echo + ["% Invalid input detected at '^' marker."])
        previous = simulated_applied(self.conn, self.device["id"])
        self.conn.execute(
            "INSERT INTO sim_device_config (device_id, lines, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET lines = excluded.lines, updated_at = excluded.updated_at",
            (self.device["id"], "\n".join(previous + list(lines)), now_iso()))
        self.conn.commit()
        return "\n".join([f"{self.device['name']}#configure terminal",
                          "Enter configuration commands, one per line.  End with CNTL/Z."] + echo +
                         [f"{self.device['name']}(config)#end"])

    def close(self):
        pass


def simulated_applied(conn, device_id) -> list[str]:
    row = conn.execute("SELECT lines FROM sim_device_config WHERE device_id = ?", (device_id,)).fetchone()
    return row["lines"].split("\n") if row and row["lines"] else []


# Comandos que abren un submodo en IOS (sus líneas siguientes van "dentro")
BLOCK_STARTERS = ("interface ", "line ", "router ", "vlan ", "archive", "ip access-list ", "class-map ",
                  "policy-map ", "key chain ")


CHILD_ORDER = {"description": 0, "ip address": 1, "shutdown": 2}


def _key(cmd: str) -> str:
    """Qué identifica a una línea para reemplazarla: 'description X' -> 'description',
    'ip address A M' -> 'ip address', 'logging trap Y' -> 'logging trap'."""
    words = cmd.split()
    two = ("ip", "logging", "ntp", "service", "spanning-tree", "switchport", "clock", "snmp-server", "login")
    if words and words[0] in two and len(words) > 1:
        return " ".join(words[:2])
    return words[0] if words else ""


def apply_config_lines(text: str, lines: list[str]) -> str:
    """Modelo sencillo de cómo IOS aplica comandos sobre la running-config (modo
    SIMULADO): reemplaza la línea con la misma clave, 'no X' la quita y
    'no shutdown' quita 'shutdown'. Suficiente para practicar cambios y rollback."""
    if not lines:
        return text
    cfg = text.rstrip("\n").split("\n")

    def block_range(header):
        i = cfg.index(header)
        j = i + 1
        while j < len(cfg) and cfg[j].startswith(" "):
            j += 1
        return i, j

    def insert_top(line):
        end = len(cfg) - 1 if cfg and cfg[-1].strip() == "end" else len(cfg)
        cfg[end:end] = [line]

    header = None
    for raw in lines:
        cmd = " ".join(raw.split())
        if not cmd:
            continue
        child = raw.startswith(" ") and header is not None
        if not child:
            header = None
            if cmd.lower().startswith(BLOCK_STARTERS):
                header = cmd
                if header not in cfg:
                    insert_top("!")
                    insert_top(header)
                continue
            if cmd == "exit":
                continue
        if cmd == "exit":
            header = None
            continue
        if header is not None:
            i, j = block_range(header)
            body = [l.strip() for l in cfg[i + 1:j]]
            if cmd == "no shutdown":
                body = [l for l in body if l != "shutdown"]
            elif cmd.startswith("no "):
                target = cmd[3:]
                body = [l for l in body if not (l == target or _key(l) == _key(target))]
                if target.startswith("ip address"):
                    body.append("no ip address")
            else:
                same = [n for n, l in enumerate(body) if _key(l) == _key(cmd)
                        or (cmd.startswith("ip address") and l == "no ip address")]
                if same:
                    body[same[0]] = cmd                     # se reemplaza en su lugar
                    body = [l for n, l in enumerate(body) if n not in same[1:]]
                else:
                    body.append(cmd)
            # IOS muestra la interfaz en un orden fijo: descripción, IP, shutdown, el resto
            body.sort(key=lambda l: CHILD_ORDER.get("ip address" if l == "no ip address" else _key(l), 9))
            cfg[i + 1:j] = [" " + l for l in body]
        else:
            top = [n for n, l in enumerate(cfg) if not l.startswith(" ")]
            if cmd.startswith("no "):
                target = cmd[3:]
                cfg[:] = [l for n, l in enumerate(cfg)
                          if l.startswith(" ") or not (l == target or l.startswith(_key(target) + " "))]
            else:
                same = [n for n in top if _key(cfg[n]) == _key(cmd) and _key(cmd) not in ("ntp server", "logging host")]
                if same:
                    cfg[same[0]] = cmd
                else:
                    insert_top(cmd)
    return "\n".join(cfg) + "\n"


def simulated_running_config(text: str, device, conn) -> str:
    """Fase 10.1: la configuración simulada refleja el INVENTARIO: el hostname es el
    nombre del equipo y la descripción de cada interfaz es la registrada en el NOC.
    Así, editar una descripción en Interfaces "cambia" el equipo simulado y la
    siguiente versión muestra la diferencia (en un equipo real el cambio se hace
    en el propio equipo)."""
    descriptions = {r["name"]: r["description"] for r in conn.execute(
        "SELECT name, description FROM interfaces WHERE device_id = ?", (device["id"],))}
    out, current = [], None
    for line in text.splitlines():
        if line.startswith("hostname "):
            line = f"hostname {device['name']}"
        if line.startswith("interface "):
            current = line.split(" ", 1)[1]
            out.append(line)
            if descriptions.get(current):
                out.append(f" description {descriptions[current]}")
            continue
        if current and line.startswith(" description ") and current in descriptions:
            if not descriptions[current]:
                out.append(line)          # sin descripción en el NOC: se deja la del equipo
            continue                      # con descripción en el NOC: ya se escribió arriba
        if not line.startswith(" "):
            current = None
        out.append(line)
    return "\n".join(out) + "\n"


def simulated_diagnostic(command: str) -> str:
    """Salida con formato IOS para el modo simulado: responde la red del laboratorio
    (192.168.100.0/24) y las de documentación; lo demás no responde."""
    kind, ip = command.split()[0], command.split()[-1]
    reach = ip.startswith(("192.168.100.", "192.0.2.", "198.51.100.", "203.0.113."))
    if kind == "ping":
        head = ["Type escape sequence to abort.",
                f"Sending 5, 100-byte ICMP Echos to {ip}, timeout is 2 seconds:"]
        if reach:
            return "\n".join(head + ["!!!!!", "Success rate is 100 percent (5/5), round-trip min/avg/max = 1/1/2 ms"])
        return "\n".join(head + [".....", "Success rate is 0 percent (0/5)"])
    lines = ["Type escape sequence to abort.", f"Tracing the route to {ip}", "VRF info: (vrf in name/id, vrf out name/id)"]
    if reach:
        lines += [f"  1 {ip} 1 msec 0 msec 1 msec"]
    else:
        lines += ["  1 192.168.100.1 1 msec 1 msec 0 msec", "  2  *  *  *", "  3  *  *  *"]
    return "\n".join(lines)


class NetmikoTransport:
    """Conexión REAL con Netmiko: por consola (cable, puerto COM) o por SSH."""

    def __init__(self, device):
        self.device = device
        self.transport = device["connection_mode"]
        self.host_key_fp = None
        self._conn = None
        if self.transport == "consola":
            self.target = device["console_port"]
        else:
            self.target = f"{device['ip']}:{Config.SSH_PORT}"

    def _params(self) -> dict:
        common = {"timeout": Config.COMMAND_TIMEOUT, "conn_timeout": Config.CONNECT_TIMEOUT,
                  "fast_cli": False}
        if self.transport == "consola":
            # Equipo prestado: SIN usuario ni contraseña. Netmiko solo trae
            # consola para Cisco (cisco_ios_serial; sirve también para IOS XE).
            return {**common, "device_type": "cisco_ios_serial", "username": "", "password": "",
                    "serial_settings": {"port": self.device["console_port"],
                                        "baudrate": Config.CONSOLE_BAUDRATE}}
        return {**common, "device_type": self.device["platform"], "host": self.device["ip"],
                "port": Config.SSH_PORT, "username": Config.SSH_USERNAME,
                "password": Config.SSH_PASSWORD}

    def open(self):
        from netmiko import ConnectHandler     # se importa aquí: las pruebas no lo necesitan
        try:
            self._conn = ConnectHandler(**self._params())
            if self.transport == "ssh":
                key = self._conn.remote_conn_pre.get_transport().get_remote_server_key()
                self.host_key_fp = ssh_fingerprint(key.asbytes())
            try:
                self._conn.enable()            # sin enable secret entra directo (modo #)
            except Exception:
                pass                           # en modo usuario los "show" básicos funcionan
        except Exception as e:                 # sin contraseñas en el mensaje
            raise ConnectionError_(self._friendly_error(e))

    def _friendly_error(self, e: Exception) -> str:
        """Mensaje en español que dice QUÉ revisar (Fase 9.2: antes salía el texto de Netmiko)."""
        text = str(e)
        where = f"({self.transport} {self.target})"
        if self.transport == "consola":
            if "not found" in text:
                ports = text.split("available devices are:")[-1].strip(" ,.") if "available" in text else ""
                return (f"No se pudo conectar {where}: el puerto {self.target} no existe en este PC. "
                        f"Puertos disponibles: {ports or 'ninguno'} (¿está conectado el cable de consola?)")
            if "denied" in text.lower() or "PermissionError" in text or "busy" in text.lower():
                return (f"No se pudo conectar {where}: el puerto {self.target} está en uso "
                        "(¿PuTTY sigue abierto? Ciérrelo y vuelva a intentar)")
        if "Authentication" in type(e).__name__:
            return f"No se pudo conectar {where}: usuario o contraseña SSH rechazados (revise el .env)"
        if "Timeout" in type(e).__name__:
            return f"No se pudo conectar {where}: el equipo no respondió a tiempo (¿IP, cable o SSH activo?)"
        first = text.splitlines()[0][:160] if text else ""
        return f"No se pudo conectar {where}: {type(e).__name__}: {first}"

    def send(self, command: str) -> str:
        # Fase 9.4: un traceroute con saltos que no responden tarda más que un "show"
        slow = command.startswith(("traceroute", "tracert", "execute traceroute"))
        try:
            return self._conn.send_command(command, read_timeout=Config.DIAG_TIMEOUT if slow
                                           else Config.COMMAND_TIMEOUT)
        except Exception as e:
            raise ConnectionError_(f"Error ejecutando '{command}': {type(e).__name__}")

    def send_config(self, lines: list[str]) -> str:
        """Fase 10.3: entra a configure terminal, envía las líneas y sale (Netmiko)."""
        try:
            return self._conn.send_config_set(lines, read_timeout=Config.COMMAND_TIMEOUT * 2)
        except Exception as e:
            raise ConnectionError_(f"Error aplicando la configuración: {type(e).__name__}")

    def close(self):
        if self._conn is not None:
            try:
                self._conn.disconnect()
            except Exception:
                pass


def make_transport(device, conn):
    """Elige el transporte según el modo. Las pruebas lo reemplazan por uno falso."""
    if device["connection_mode"] == "simulado":
        return SimulatedTransport(device, conn)
    return NetmikoTransport(device)


def ssh_fingerprint(key_bytes: bytes) -> str:
    """Huella como la muestra OpenSSH: SHA256:base64 sin '='."""
    return "SHA256:" + base64.b64encode(hashlib.sha256(key_bytes).digest()).decode().rstrip("=")


# ---------------------------------------------------------------------------
# 2. IDENTIDAD DEL EQUIPO FÍSICO (a partir de show version / equivalentes)
# ---------------------------------------------------------------------------
def parse_identity(platform: str, text: str) -> dict:
    """Devuelve {serial, model, version, warnings}. Lo que no encuentre queda en None."""
    def find(pattern, flags=re.M):
        m = re.search(pattern, text or "", flags)
        return m.group(1).strip() if m else None

    out = {"serial": None, "model": None, "version": None, "warnings": []}
    if platform in ("cisco_ios", "cisco_xe"):
        # 2960: "System serial number : FOC..."; IOS XE: "Processor board ID FGL..."
        out["serial"] = find(r"^System [Ss]erial [Nn]umber\s*:\s*(\S+)") or find(r"Processor board ID (\S+)")
        out["model"] = find(r"^Model [Nn]umber\s*:\s*(\S+)") or find(r"^cisco (\S+) .*processor")
        out["version"] = find(r"Version ([\w.()]+)")
        image = (find(r'System image file is "([^"]+)"') or "") + " " + (find(r"\(([\w-]+)\), Version") or "")
        if platform == "cisco_ios" and "k9" not in image.lower():
            out["warnings"].append("La imagen no tiene criptografía (k9): el equipo no soporta SSH; use el modo consola")
        mode = find(r"Router operating mode:\s*(.+)$")
        if platform == "cisco_xe" and mode and "autonomous" not in mode.lower():
            out["warnings"].append(f"Router en modo '{mode}' (SD-WAN): la consola es distinta; "
                                   "cámbielo a modo autónomo antes de las pruebas")
    elif platform == "fortinet":
        out["serial"] = find(r"^Serial-Number:\s*(\S+)")
        out["model"] = find(r"^Version:\s*(\S+)")
        out["version"] = find(r"^Version:\s*\S+\s+(v[\w.]+)")
    elif platform == "huawei":
        out["serial"] = find(r"ESN[^:]*:\s*(\S+)")
        out["model"] = find(r"^(?:HUAWEI|Huawei)\s+(\S+)\s.*uptime") or find(r"\((\S+)\s+V\d")
        out["version"] = find(r"Version\s+([\w.]+)")
    if not out["serial"]:
        out["warnings"].append("No se pudo leer el número de serie: no se puede confirmar qué equipo físico es")
    return out


# ---------------------------------------------------------------------------
# 3. VALIDACIÓN PREVIA Y RESERVA DEL EQUIPO
# ---------------------------------------------------------------------------
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(device) -> threading.Lock:
    # Un puerto COM es UNO solo aunque se use para varios equipos (se cambia el cable)
    key = (f"port:{device['console_port']}" if device["connection_mode"] == "consola"
           else f"dev:{device['id']}")
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def readiness_errors(device) -> list[str]:
    """¿Está el equipo listo para conectarse? Lista de problemas (vacía = listo)."""
    mode, errors = device["connection_mode"], []
    if mode == "ninguno":
        return ["El equipo no tiene modo de conexión (solo recibe Syslog). Edítelo en el inventario"]
    if device["platform"] not in PLATFORMS.get(device["vendor"], ()):
        errors.append(f"Plataforma '{device['platform']}' no válida para {device['vendor']}")
    if mode == "consola":
        if device["vendor"] != "Cisco":
            errors.append("La conexión por consola solo está disponible para Cisco")
        if not RE_CONSOLE_PORT.match(device["console_port"] or ""):
            errors.append("Falta el puerto de consola (ej. COM3)")
    if mode == "ssh" and not (Config.SSH_USERNAME and Config.SSH_PASSWORD):
        errors.append("Faltan SSH_USERNAME y SSH_PASSWORD en el archivo .env")
    return errors


# ---------------------------------------------------------------------------
# 4. LA SESIÓN
# ---------------------------------------------------------------------------
def run_session(conn, device, commands: list[str], user: str, diagnostic: bool = False,
                sanitize=None) -> tuple[dict, int]:
    """Ejecuta una sesión completa. Devuelve (resultado, código HTTP).

    sanitize (Fase 10.1): función que limpia la salida ANTES de guardarla. Solo
    la usa la captura de configuración (app/configversions.py) para ocultar los
    secretos; con ella se acepta "show running-config", que la sesión normal
    sigue bloqueando."""
    # --- 1. Validar todo ANTES de conectar ----------------------------------
    problems = readiness_errors(device)
    if problems:
        return {"errors": problems}, 400
    if len(commands) > MAX_COMMANDS:
        return {"errors": [f"Máximo {MAX_COMMANDS} comandos por sesión"]}, 400
    blocked = []
    for cmd in commands:
        ok, reason = check_command(device["vendor"], cmd, user, diagnostic=diagnostic,
                                   capture=sanitize is not None)
        if not ok:
            blocked.append(f"'{cmd[:60]}': {reason}")
            audit(conn, user, "device.command_blocked", "devices", device["id"],
                  f"{device['name']}: {cmd[:120]!r} -> {reason}", "bloqueado")
    if blocked:
        return {"errors": ["No se abrió la conexión: hay comandos bloqueados"] + blocked}, 403

    # --- 2. Reservar ----------------------------------------------------------
    lock = _lock_for(device)
    if not lock.acquire(blocking=False):
        return {"errors": ["El equipo (o el puerto de consola) está ocupado con otra sesión"]}, 409
    try:
        return _session(conn, device, commands, user, sanitize)
    finally:
        lock.release()


def _session(conn, device, commands, user, sanitize=None):
    transport = make_transport(device, conn)
    cur = conn.execute(
        "INSERT INTO device_sessions (device_id, device_name, transport, target, started_by, started_at, "
        "is_simulated) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (device["id"], device["name"], transport.transport, transport.target, user, now_iso(),
         int(transport.transport == "simulado" or bool(device["is_simulated"]))))
    conn.commit()
    sid = cur.lastrowid
    warnings = []

    def finish(status, error=None, http=200):
        n = conn.execute("SELECT COUNT(*) FROM device_commands WHERE session_id = ?", (sid,)).fetchone()[0]
        conn.execute("UPDATE device_sessions SET status = ?, error = ?, ended_at = ?, warnings = ?, "
                     "commands_count = ? WHERE id = ?",
                     (status, error, now_iso(), " | ".join(warnings) or None, n, sid))
        conn.commit()
        where = transport.transport + ("" if transport.target == transport.transport else f" {transport.target}")
        audit(conn, user, "device.session", "device_sessions", sid,
              f"{device['name']} {where} estado={status} comandos={n}"
              + (f" error={error}" if error else ""), "ok" if status == "cerrada" else "alerta")
        result = get_session(conn, sid)
        if error:
            result["errors"] = [error]
        return result, http

    try:
        transport.open()
        # --- Llave SSH (solo equipos fijos): fijada la primera vez -------------
        if transport.transport == "ssh" and transport.host_key_fp:
            conn.execute("UPDATE device_sessions SET host_key_fp = ? WHERE id = ?", (transport.host_key_fp, sid))
            if device["host_key_fp"] and device["host_key_fp"] != transport.host_key_fp:
                audit(conn, user, "device.hostkey_cambio", "devices", device["id"],
                      f"{device['name']}: esperada {device['host_key_fp']} recibida {transport.host_key_fp}",
                      "alerta")
                return finish("fallida", "La llave SSH del equipo CAMBIÓ: posible suplantación. "
                                         "Sesión abortada sin enviar comandos", 409)
            if not device["host_key_fp"]:
                conn.execute("UPDATE devices SET host_key_fp = ? WHERE id = ?", (transport.host_key_fp, device["id"]))
                audit(conn, user, "device.hostkey_registrada", "devices", device["id"],
                      f"{device['name']}: {transport.host_key_fp}")

        # --- Identificación del equipo físico ----------------------------------
        id_cmd = IDENTITY_COMMAND[device["platform"]]
        identity = parse_identity(device["platform"], _run(conn, transport, sid, id_cmd, user))
        warnings += identity["warnings"]
        if device["serial_number"] and identity["serial"] and identity["serial"] != device["serial_number"]:
            warnings.append(f"EQUIPO FÍSICO DISTINTO: antes {device['serial_number']}, ahora {identity['serial']}")
            audit(conn, user, "device.serial_cambio", "devices", device["id"],
                  f"{device['name']}: serie anterior {device['serial_number']} -> {identity['serial']}", "alerta")
        conn.execute("UPDATE device_sessions SET serial_number = ?, model = ?, os_version = ? WHERE id = ?",
                     (identity["serial"], identity["model"], identity["version"], sid))
        conn.execute("UPDATE devices SET serial_number = COALESCE(?, serial_number), detected_model = ?, "
                     "detected_version = ?, last_identified_at = ? WHERE id = ?",
                     (identity["serial"], identity["model"], identity["version"], now_iso(), device["id"]))
        conn.commit()

        # --- Comandos pedidos ------------------------------------------------------
        for cmd in commands:
            if cmd.strip().lower() != id_cmd:          # show version ya se ejecutó
                _run(conn, transport, sid, cmd, user, sanitize)
        return finish("cerrada")
    except ConnectionError_ as e:
        return finish("fallida", str(e), 502)
    finally:
        transport.close()


def _run(conn, transport, sid, command, user, sanitize=None) -> str:
    """Envía un comando y lo registra con su salida y la huella SHA-256 de la salida.
    Con sanitize (captura de configuración) se guarda la salida YA LIMPIA (sin
    secretos) y completa: la huella corresponde a lo guardado."""
    started, t0 = now_iso(), time.monotonic()
    limit = MAX_OUTPUT
    try:
        output, status = transport.send(command), "ok"
        if sanitize is not None:
            output, limit = sanitize(output), MAX_CAPTURE
    except ConnectionError_ as e:
        output, status = str(e), "error"
    ms = int((time.monotonic() - t0) * 1000)
    conn.execute("INSERT INTO device_commands (session_id, command, requested_by, started_at, duration_ms, "
                 "status, output, output_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (sid, command, user, started, ms, status, output[:limit],
                  hashlib.sha256(output.encode("utf-8", "replace")).hexdigest()))
    conn.commit()
    audit(conn, user, "device.command", "device_sessions", sid, f"{command} ({ms} ms) {status}",
          "ok" if status == "ok" else "alerta")
    if status == "error":
        raise ConnectionError_(output)
    return output


RE_CONFIG_ERROR = re.compile(r"^\s*%\s*(Invalid|Incomplete|Ambiguous|Unknown|Bad|Unrecognized|Error)", re.M | re.I)


def run_config(conn, device, lines: list[str], user: str, expected_serial: str | None = None,
               label: str = "cambio") -> tuple[dict, int]:
    """Fase 10.3: aplica líneas de configuración en una sesión trazable.

    Lo llama SOLO la ejecución de un cambio APROBADO (app/changeexec.py), que ya
    validó los comandos. Igual se repite la defensa: un agente de IA nunca aplica
    configuración, y si responde otro equipo físico no se envía nada."""
    if user == "asistente_ia":
        return {"errors": ["Un agente de IA no aplica configuración"]}, 403
    problems = readiness_errors(device)
    if problems:
        return {"errors": problems}, 400
    lock = _lock_for(device)
    if not lock.acquire(blocking=False):
        return {"errors": ["El equipo (o el puerto de consola) está ocupado con otra sesión"]}, 409
    try:
        transport = make_transport(device, conn)
        cur = conn.execute(
            "INSERT INTO device_sessions (device_id, device_name, transport, target, started_by, started_at, "
            "is_simulated) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (device["id"], device["name"], transport.transport, transport.target, user, now_iso(),
             int(transport.transport == "simulado" or bool(device["is_simulated"]))))
        conn.commit()
        sid = cur.lastrowid
        status, error = "cerrada", None
        try:
            transport.open()
            identity = parse_identity(device["platform"], _run(conn, transport, sid, IDENTITY_COMMAND[device["platform"]], user))
            conn.execute("UPDATE device_sessions SET serial_number = ?, model = ?, os_version = ? WHERE id = ?",
                         (identity["serial"], identity["model"], identity["version"], sid))
            if expected_serial and identity["serial"] and identity["serial"] != expected_serial:
                status, error = "fallida", (f"Respondió OTRO equipo físico ({identity['serial']}, se esperaba "
                                            f"{expected_serial}): no se aplicó nada")
            else:
                started, t0 = now_iso(), time.monotonic()
                try:
                    output, cmd_status = transport.send_config(lines), "ok"
                except ConnectionError_ as e:
                    output, cmd_status = str(e), "error"
                if cmd_status == "ok" and RE_CONFIG_ERROR.search(output):
                    cmd_status = "error"
                conn.execute(
                    "INSERT INTO device_commands (session_id, command, requested_by, started_at, duration_ms, "
                    "status, output, output_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (sid, f"configure terminal ({label}: {len(lines)} líneas)", user, started,
                     int((time.monotonic() - t0) * 1000), cmd_status, output[:MAX_OUTPUT],
                     hashlib.sha256(output.encode("utf-8", "replace")).hexdigest()))
                audit(conn, user, "device.config_apply", "device_sessions", sid,
                      f"{device['name']}: {label}, {len(lines)} líneas -> {cmd_status}",
                      "ok" if cmd_status == "ok" else "alerta")
                if cmd_status != "ok":
                    error = next((l.strip() for l in output.splitlines() if RE_CONFIG_ERROR.match(l)),
                                 output.splitlines()[-1] if output else "error")
                    status = "fallida"
        except ConnectionError_ as e:
            status, error = "fallida", str(e)
        finally:
            transport.close()
        n = conn.execute("SELECT COUNT(*) FROM device_commands WHERE session_id = ?", (sid,)).fetchone()[0]
        conn.execute("UPDATE device_sessions SET status = ?, error = ?, ended_at = ?, commands_count = ? WHERE id = ?",
                     (status, error, now_iso(), n, sid))
        conn.commit()
        result = get_session(conn, sid)
        # Fase 10.3: respondió otro equipo físico -> quien llama NO debe hacer rollback
        result["wrong_device"] = bool(expected_serial and result["serial_number"] not in (None, expected_serial))
        if error:
            result["errors"] = [error]
        return result, 200 if status == "cerrada" else 502
    finally:
        lock.release()


def get_session(conn, sid) -> dict | None:
    row = conn.execute("SELECT * FROM device_sessions WHERE id = ?", (sid,)).fetchone()
    if row is None:
        return None
    s = dict(row)
    s["warnings"] = (s["warnings"] or "").split(" | ") if s["warnings"] else []
    s["commands"] = [dict(r) for r in conn.execute(
        "SELECT * FROM device_commands WHERE session_id = ? ORDER BY id", (sid,))]
    return s


# ---------------------------------------------------------------------------
# 5. API
# ---------------------------------------------------------------------------
@bp.post("/devices/<int:device_id>/session")
def open_session(device_id):
    conn = get_db()
    device = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if device is None:
        return jsonify(errors=["Equipo no encontrado"]), 404
    data = request.get_json(silent=True) or {}
    commands = data.get("commands") or []
    if not isinstance(commands, list) or not all(isinstance(c, str) for c in commands):
        return jsonify(errors=["'commands' debe ser una lista de textos"]), 400
    result, status = run_session(conn, device, [c.strip() for c in commands if c.strip()], session_actor())
    return jsonify(result), status


@bp.get("/devices/<int:device_id>/sessions")
def list_sessions(device_id):
    rows = get_db().execute(
        "SELECT id, transport, target, started_by, started_at, ended_at, status, error, serial_number, "
        "model, os_version, warnings, commands_count, is_simulated FROM device_sessions "
        "WHERE device_id = ? ORDER BY id DESC LIMIT 50", (device_id,)).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/sessions/<int:sid>")
def session_detail(sid):
    s = get_session(get_db(), sid)
    if s is None:
        return jsonify(error="Sesión no encontrada"), 404
    return jsonify(s)
