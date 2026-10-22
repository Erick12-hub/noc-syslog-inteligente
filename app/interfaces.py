"""
Fase 8.4: interfaces de cada equipo del inventario.

    GET    /api/devices/<id>/interfaces             Listar las interfaces del equipo
    POST   /api/devices/<id>/interfaces             Registrar una interfaz
    PUT    /api/devices/<id>/interfaces/<iid>       Editar nombre, descripción o estado
    DELETE /api/devices/<id>/interfaces/<iid>       Eliminar

Para qué sirve: la ingesta compara la interfaz que trae cada evento con esta
lista. Si el equipo TIENE interfaces registradas y el evento menciona otra,
el evento se marca 'interfaz_desconocida' (ver app/ingest.py).

El nombre se valida SEGÚN EL FABRICANTE del equipo: un "port1" es válido en
un FortiGate pero no en un router Cisco, y un "GigabitEthernet0/1" no existe
en un FortiGate. Los nombres cortos de Cisco/Huawei (Gi0/1, GE0/0/1) se
guardan con el nombre largo, igual que hace el parser con los eventos.

Permisos (app/auth.py, regla por defecto): consultar = todos los roles;
crear, editar y eliminar = operador y administrador. Todo queda en la auditoría.
"""
import re
import sqlite3

from flask import Blueprint, jsonify, request

from .auth import actor
from .db import audit, get_db, now_iso
from .syslog_parser import IFACE_ABBR, is_valid_interface

bp = Blueprint("interfaces", __name__, url_prefix="/api/devices")

STATUSES = ("up", "down", "admin_down", "desconocido")
MAX_DESCRIPTION = 100
MAX_PER_DEVICE = 200          # límite sano: evita llenar la base por error o abuso

# Numeración de Cisco y Huawei:  0  |  0/1  |  0/0/1  |  1/0/1/2  |  0/0/1.100 (subinterfaz)
_NUM = r"\d{1,4}(?:/\d{1,4}){0,3}(?:\.\d{1,4})?"

# Familias de interfaces por fabricante (nombre largo, el que se guarda)
CISCO_FAMILIES = ("GigabitEthernet", "TenGigabitEthernet", "TwentyFiveGigabitEthernet",
                  "TwentyFiveGigE", "FortyGigabitEthernet", "HundredGigabitEthernet", "HundredGigE",
                  "FastEthernet", "Ethernet",
                  "Serial", "Loopback", "Vlan", "Port-channel", "Tunnel")
HUAWEI_FAMILIES = ("GigabitEthernet", "XGigabitEthernet", "Ethernet", "Vlanif", "LoopBack",
                   "Loopback", "Eth-Trunk", "Tunnel", "MEth", "NULL")

RE_BY_VENDOR = {
    "Cisco": re.compile(rf"^(?:{'|'.join(CISCO_FAMILIES)}){_NUM}$"),
    "Huawei": re.compile(rf"^(?:{'|'.join(map(re.escape, HUAWEI_FAMILIES))}){_NUM}$"),
    # FortiOS: nombre libre de hasta 15 caracteres, sin "/" ni espacios (port1, wan1, internal, dmz)
    "Fortinet": re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,14}$"),
}

EXAMPLES = {
    "Cisco": "GigabitEthernet0/0/1, Gi0/1, Vlan10, Loopback0, Port-channel1",
    "Huawei": "GigabitEthernet0/0/1, GE0/0/1, Vlanif10, Eth-Trunk1, LoopBack0",
    "Fortinet": "port1, wan1, internal, dmz (máx. 15 caracteres, sin '/')",
    "Otro": "letras, números y . _ / : - (máx. 48 caracteres)",
}


def normalize_for_vendor(vendor: str, name: str) -> str:
    """
    Deja el nombre como lo muestra el equipo:
      Cisco/Huawei: 'Gi0/1' o 'gigabitethernet0/1' -> 'GigabitEthernet0/1'
      FortiGate:    se deja igual (los nombres los define el administrador).
    """
    name = (name or "").strip()
    if vendor == "Fortinet":
        return name
    # Abreviatura sin importar mayúsculas: gi0/1, Gi0/1, GI0/1 -> GigabitEthernet0/1
    m = re.match(r"^(?P<abbr>[A-Za-z\-]+?)(?P<num>\d.*)$", name)
    abbr = {k.lower(): v for k, v in IFACE_ABBR.items()}
    if m and m["abbr"].lower() in abbr:
        name = abbr[m["abbr"].lower()] + m["num"]
    families = HUAWEI_FAMILIES if vendor == "Huawei" else CISCO_FAMILIES
    # La familia más larga primero: "TenGigabitEthernet" antes que "GigabitEthernet"
    for family in sorted(families, key=len, reverse=True):
        if name.lower().startswith(family.lower()) and name[len(family):][:1].isdigit():
            return family + name[len(family):]
    return name


def validate_interface_name(vendor: str, name: str) -> list[str]:
    """Devuelve la lista de errores del nombre (vacía si es válido para ese fabricante)."""
    if not name:
        return ["El nombre de la interfaz es obligatorio"]
    if not is_valid_interface(name):        # sintaxis general (bloquea ';', espacios, '<'...)
        return [f"Nombre de interfaz inválido: {name!r}"]
    rx = RE_BY_VENDOR.get(vendor)
    if rx and not rx.match(name):
        return [f"'{name}' no es una interfaz válida de {vendor}. Ejemplos: {EXAMPLES[vendor]}"]
    return []


def validate(data: dict, vendor: str, partial: bool = False) -> tuple[dict, list]:
    """Valida y normaliza nombre, descripción y estado. Junta TODOS los errores."""
    clean, errors = {}, []
    if not partial or data.get("name") is not None:
        name = normalize_for_vendor(vendor, str(data.get("name") or ""))
        errors += validate_interface_name(vendor, name)
        clean["name"] = name
    if data.get("description") is not None:
        desc = str(data["description"]).strip()
        if len(desc) > MAX_DESCRIPTION:
            errors.append(f"La descripción supera {MAX_DESCRIPTION} caracteres")
        clean["description"] = desc or None
    if data.get("status") is not None:
        if data["status"] not in STATUSES:
            errors.append(f"Estado inválido. Opciones: {', '.join(STATUSES)}")
        clean["status"] = data["status"]
    return clean, errors


def _device(conn, device_id):
    return conn.execute("SELECT id, name, vendor FROM devices WHERE id = ?", (device_id,)).fetchone()


def _interface(conn, device_id, iface_id):
    return conn.execute("SELECT * FROM interfaces WHERE id = ? AND device_id = ?",
                        (iface_id, device_id)).fetchone()


@bp.get("/<int:device_id>/interfaces")
def list_interfaces(device_id):
    conn = get_db()
    dev = _device(conn, device_id)
    if dev is None:
        return jsonify(error="Equipo no encontrado"), 404
    rows = conn.execute("SELECT * FROM interfaces WHERE device_id = ? ORDER BY name",
                        (device_id,)).fetchall()
    return jsonify(device=dict(dev), example=EXAMPLES.get(dev["vendor"], ""),
                   rows=[dict(r) for r in rows])


@bp.post("/<int:device_id>/interfaces")
def create_interface(device_id):
    conn = get_db()
    dev = _device(conn, device_id)
    if dev is None:
        return jsonify(error="Equipo no encontrado"), 404
    data, errors = validate(request.get_json(silent=True) or {}, dev["vendor"])
    count = conn.execute("SELECT COUNT(*) FROM interfaces WHERE device_id = ?", (device_id,)).fetchone()[0]
    if count >= MAX_PER_DEVICE:
        errors.append(f"El equipo ya tiene el máximo de {MAX_PER_DEVICE} interfaces")
    if errors:
        return jsonify(errors=errors), 400

    ts = now_iso()
    try:
        cur = conn.execute(
            "INSERT INTO interfaces (device_id, name, description, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (device_id, data["name"], data.get("description"), data.get("status", "desconocido"), ts, ts))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify(errors=[f"{dev['name']} ya tiene la interfaz {data['name']}"]), 409

    audit(conn, actor(), "interface.create", "interfaces", cur.lastrowid,
          f"{dev['name']} {data['name']} estado={data.get('status', 'desconocido')}")
    return jsonify(dict(_interface(conn, device_id, cur.lastrowid))), 201


@bp.put("/<int:device_id>/interfaces/<int:iface_id>")
def update_interface(device_id, iface_id):
    conn = get_db()
    dev = _device(conn, device_id)
    row = _interface(conn, device_id, iface_id) if dev else None
    if row is None:                       # también si la interfaz es de OTRO equipo
        return jsonify(error="Interfaz no encontrada"), 404
    data, errors = validate(request.get_json(silent=True) or {}, dev["vendor"], partial=True)
    if errors:
        return jsonify(errors=errors), 400
    if not data:
        return jsonify(errors=["No se enviaron campos para actualizar"]), 400

    data["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in data)      # los nombres de columna vienen de validate()
    try:
        conn.execute(f"UPDATE interfaces SET {sets} WHERE id = ?", (*data.values(), iface_id))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify(errors=[f"{dev['name']} ya tiene la interfaz {data['name']}"]), 409

    changed = ", ".join(f"{k}={v}" for k, v in data.items() if k != "updated_at")
    audit(conn, actor(), "interface.update", "interfaces", iface_id, f"{dev['name']} {row['name']}: {changed}")
    return jsonify(dict(_interface(conn, device_id, iface_id)))


@bp.delete("/<int:device_id>/interfaces/<int:iface_id>")
def delete_interface(device_id, iface_id):
    conn = get_db()
    dev = _device(conn, device_id)
    row = _interface(conn, device_id, iface_id) if dev else None
    if row is None:
        return jsonify(error="Interfaz no encontrada"), 404
    conn.execute("DELETE FROM interfaces WHERE id = ?", (iface_id,))
    conn.commit()
    audit(conn, actor(), "interface.delete", "interfaces", iface_id, f"{dev['name']} {row['name']}")
    return jsonify(deleted=iface_id)


def is_known_interface(conn, device_id, name) -> bool | None:
    """
    Usado por la ingesta. Devuelve:
      None  -> el equipo no tiene interfaces registradas (no se puede comparar)
      True  -> la interfaz (o su interfaz madre, si es subinterfaz) está registrada
      False -> el equipo tiene interfaces y esta NO es una de ellas
    """
    if device_id is None or not name:
        return None
    if conn.execute("SELECT 1 FROM interfaces WHERE device_id = ? LIMIT 1", (device_id,)).fetchone() is None:
        return None
    candidates = [name]
    if "." in name:                       # GigabitEthernet0/0/1.100 -> también vale GigabitEthernet0/0/1
        candidates.append(name.split(".", 1)[0])
    marks = ", ".join("?" for _ in candidates)
    found = conn.execute(f"SELECT 1 FROM interfaces WHERE device_id = ? AND name IN ({marks}) LIMIT 1",
                         (device_id, *candidates)).fetchone()
    return found is not None


# ===========================================================================
# Fase 9.3: INTERFACES REALES leídas del equipo
#
#   POST /api/devices/<id>/interfaces/sync   {"remove_missing": false}
#
# El NOC se conecta (app/connector.py), ejecuta el comando de interfaces de
# la marca y compara la salida con la tabla:
#   nuevas         -> se registran (source = 'equipo')
#   actualizadas   -> cambió el estado o la IP
#   sin cambios    -> solo se actualiza last_seen_at
#   desaparecidas  -> están en la tabla pero el equipo ya no las reporta
#                     (se eliminan solo si se pide: remove_missing)
#   inválidas      -> nombres que no pasan la validación de la marca: la
#                     salida del equipo también es un DATO NO CONFIABLE
# ===========================================================================
SYNC_COMMAND = {"cisco_ios": "show ip interface brief", "cisco_xe": "show ip interface brief",
                "huawei": "display ip interface brief", "fortinet": "get system interface physical"}

# Cisco:  GigabitEthernet0/0/1   unassigned   YES unset  administratively down down
RE_CISCO_ROW = re.compile(
    r"^(?P<name>\S+)\s+(?P<ip>\S+)\s+(?:YES|NO)\s+\S+\s+"
    r"(?P<status>administratively down|up|down|deleted)\s+(?P<proto>up|down)\s*$")
# Huawei: GigabitEthernet0/0/1   192.0.2.1/24   up   up(s)   /   *down   down
RE_HUAWEI_ROW = re.compile(
    r"^(?P<name>[A-Za-z][\w/.\-]*)\s+(?P<ip>\S+)\s+(?P<status>\*?down|up|\^down)\S*\s+(?P<proto>up|down)\S*\s*$")
# Fortinet:     ==[port1]   ...   ip: 192.0.2.1 255.255.255.0   status: up
RE_FORTI_NAME = re.compile(r"==\[(?P<name>[^\]]+)\]")
RE_FORTI_IP = re.compile(r"\bip:\s*(?P<ip>\d{1,3}(?:\.\d{1,3}){3})")
RE_FORTI_STATUS = re.compile(r"\bstatus:\s*(?P<status>up|down)")


def parse_interfaces(platform: str, text: str) -> list[dict]:
    """Salida del comando -> [{name, ip, status}] (status: up | down | admin_down)."""
    rows = []
    for line in (text or "").splitlines():
        line = line.rstrip()
        if platform in ("cisco_ios", "cisco_xe"):
            m = RE_CISCO_ROW.match(line)
            if not m or m["status"] == "deleted":
                continue
            status = ("admin_down" if m["status"].startswith("administratively")
                      else "up" if m["status"] == "up" and m["proto"] == "up" else "down")
            ip = m["ip"]
        elif platform == "huawei":
            m = RE_HUAWEI_ROW.match(line)
            if not m or m["name"] in ("Interface",):
                continue
            raw = m["status"]
            status = "admin_down" if raw.startswith("*") else "up" if raw == "up" and m["proto"] == "up" else "down"
            ip = m["ip"].split("/")[0]
        elif platform == "fortinet":
            m = RE_FORTI_NAME.search(line)
            if not m:
                continue
            ipm, stm = RE_FORTI_IP.search(line), RE_FORTI_STATUS.search(line)
            status = stm["status"] if stm else "desconocido"
            ip = ipm["ip"] if ipm else None
            rows.append({"name": m["name"], "ip": ip if ip and ip != "0.0.0.0" else None, "status": status})
            continue
        else:
            return []
        rows.append({"name": m["name"], "ip": None if ip.lower() in ("unassigned", "unnumbered") else ip,
                     "status": status})
    return rows


def apply_sync(conn, device, rows: list[dict], user: str, remove_missing: bool = False) -> dict:
    """Compara lo que reportó el equipo con la tabla y la actualiza. Devuelve el resumen."""
    vendor, ts = device["vendor"], now_iso()
    summary = {"nuevas": [], "actualizadas": [], "sin_cambios": [], "desaparecidas": [],
               "eliminadas": [], "invalidas": []}
    current = {r["name"].lower(): r for r in conn.execute(
        "SELECT * FROM interfaces WHERE device_id = ?", (device["id"],))}
    seen = set()
    for row in rows:
        name = normalize_for_vendor(vendor, row["name"])
        if validate_interface_name(vendor, name):           # dato no confiable: se valida
            summary["invalidas"].append(row["name"][:48])
            continue
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        old = current.get(name.lower())
        if old is None:
            if len(current) + len(summary["nuevas"]) >= MAX_PER_DEVICE:
                summary["invalidas"].append(f"{name} (límite de {MAX_PER_DEVICE})")
                continue
            conn.execute("INSERT INTO interfaces (device_id, name, description, status, created_at, updated_at, "
                         "ip_address, source, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'equipo', ?)",
                         (device["id"], name, "Leída del equipo", row["status"], ts, ts, row["ip"], ts))
            summary["nuevas"].append(name)
        elif old["status"] != row["status"] or (old["ip_address"] or None) != row["ip"]:
            conn.execute("UPDATE interfaces SET status = ?, ip_address = ?, updated_at = ?, last_seen_at = ? "
                         "WHERE id = ?", (row["status"], row["ip"], ts, ts, old["id"]))
            summary["actualizadas"].append(f"{name}: {old['status']} -> {row['status']}"
                                           + (f", IP {old['ip_address'] or '-'} -> {row['ip'] or '-'}"
                                              if (old["ip_address"] or None) != row["ip"] else ""))
        else:
            conn.execute("UPDATE interfaces SET last_seen_at = ? WHERE id = ?", (ts, old["id"]))
            summary["sin_cambios"].append(name)
    for key, old in current.items():
        if key not in seen:
            summary["desaparecidas"].append(old["name"])
            if remove_missing:
                conn.execute("DELETE FROM interfaces WHERE id = ?", (old["id"],))
                summary["eliminadas"].append(old["name"])
    conn.commit()
    counts = {k: len(v) for k, v in summary.items()}
    audit(conn, user, "interface.sync", "devices", device["id"],
          f"{device['name']}: " + " ".join(f"{k}={v}" for k, v in counts.items()),
          "alerta" if summary["desaparecidas"] or summary["invalidas"] else "ok")
    return summary


@bp.post("/<int:device_id>/interfaces/sync")
def sync_interfaces(device_id):
    from .connector import run_session           # import tardío: evita importaciones circulares
    conn = get_db()
    device = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if device is None:
        return jsonify(error="Equipo no encontrado"), 404
    command = SYNC_COMMAND.get(device["platform"])
    if command is None:
        return jsonify(errors=["Elija la plataforma del equipo en el inventario para leer sus interfaces"]), 400
    data = request.get_json(silent=True) or {}
    user = actor()
    result, status = run_session(conn, device, [command], user)
    if status != 200:
        return jsonify(result), status
    output = next((c["output"] for c in result["commands"] if c["command"] == command), "")
    rows = parse_interfaces(device["platform"], output)
    if not rows:
        return jsonify(errors=["El equipo respondió, pero no se reconoció ninguna interfaz en la salida"],
                       session=result["id"]), 502
    summary = apply_sync(conn, device, rows, user, bool(data.get("remove_missing")))
    return jsonify(session=result["id"], serial_number=result["serial_number"], summary=summary,
                   warnings=result["warnings"])
