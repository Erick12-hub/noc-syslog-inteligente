"""
API REST del inventario de dispositivos (CRUD).

    GET    /api/devices          Listar
    GET    /api/devices/<id>     Consultar uno
    POST   /api/devices          Crear
    PUT    /api/devices/<id>     Editar (se pueden enviar solo algunos campos)
    DELETE /api/devices/<id>     Eliminar

Toda escritura se valida antes de llegar a la base de datos y queda en la
auditoría con el operador responsable.
"""
import ipaddress
import re
import sqlite3

from flask import Blueprint, jsonify, request

from .auth import actor
from .db import audit, get_db, now_iso

bp = Blueprint("devices", __name__, url_prefix="/api/devices")

VENDORS = ("Cisco", "Fortinet", "Huawei", "Otro")
STATUSES = ("activo", "alerta", "caido", "mantenimiento", "desconocido")
RE_NAME = re.compile(r"^[A-Za-z0-9._-]{2,64}$")   # sin espacios ni símbolos raros
TEXT_FIELDS = ("model", "version", "location")
MAX_TEXT = 100
# Fase 9.1: conexión con el equipo (ver app/connector.py)
CONNECTION_MODES = ("ninguno", "simulado", "consola", "ssh")
PLATFORMS = ("cisco_ios", "cisco_xe", "fortinet", "huawei")
PLATFORM_VENDOR = {"cisco_ios": "Cisco", "cisco_xe": "Cisco", "fortinet": "Fortinet", "huawei": "Huawei"}
RE_CONSOLE_PORT = re.compile(r"^(COM\d{1,3}|/dev/tty[A-Za-z0-9]{1,12})$")


def _operator() -> str:
    """Fase 8: responsable = usuario de la sesión (ver app/auth.py)."""
    return actor()


def validate(data: dict, partial: bool = False) -> tuple[dict, list]:
    """
    Valida y normaliza los datos de un equipo.
    Devuelve (datos_limpios, lista_de_errores). partial=True para edición.
    """
    clean, errors = {}, []

    def present(field):
        return field in data and data[field] is not None

    # Campos obligatorios al crear
    if not partial:
        for field in ("name", "ip", "vendor"):
            if not present(field) or str(data[field]).strip() == "":
                errors.append(f"El campo '{field}' es obligatorio")

    if present("name"):
        name = str(data["name"]).strip()
        if not RE_NAME.match(name):
            errors.append("Nombre inválido: 2-64 caracteres, solo letras, números, '.', '_' o '-'")
        clean["name"] = name

    if present("ip"):
        try:
            # ipaddress valida IPv4 e IPv6 y normaliza el formato
            clean["ip"] = str(ipaddress.ip_address(str(data["ip"]).strip()))
        except ValueError:
            errors.append(f"IP inválida: {data['ip']!r}")

    if present("vendor"):
        if data["vendor"] not in VENDORS:
            errors.append(f"Marca inválida. Opciones: {', '.join(VENDORS)}")
        clean["vendor"] = data["vendor"]

    if present("status"):
        if data["status"] not in STATUSES:
            errors.append(f"Estado inválido. Opciones: {', '.join(STATUSES)}")
        clean["status"] = data["status"]

    for field in TEXT_FIELDS:
        if present(field):
            value = str(data[field]).strip()
            if len(value) > MAX_TEXT:
                errors.append(f"'{field}' supera {MAX_TEXT} caracteres")
            clean[field] = value

    for field in ("authorized", "is_simulated"):
        if present(field):
            clean[field] = 1 if data[field] in (True, 1, "1", "true", "on") else 0

    # --- Fase 9.1: modo de conexión, plataforma y puerto de consola ---------
    if present("connection_mode"):
        if data["connection_mode"] not in CONNECTION_MODES:
            errors.append(f"Modo de conexión inválido. Opciones: {', '.join(CONNECTION_MODES)}")
        clean["connection_mode"] = data["connection_mode"]
    if "platform" in data:
        value = data["platform"] or None
        if value is not None and value not in PLATFORMS:
            errors.append(f"Plataforma inválida. Opciones: {', '.join(PLATFORMS)}")
        clean["platform"] = value
    if "console_port" in data:
        value = (str(data["console_port"] or "").strip().upper() or None)
        if value and value.startswith("/DEV/"):
            value = str(data["console_port"]).strip()          # Linux: se respeta el nombre
        if value is not None and not RE_CONSOLE_PORT.match(value):
            errors.append("Puerto de consola inválido (ej. COM3 o /dev/ttyUSB0)")
        clean["console_port"] = value
    return clean, errors


def check_connection(merged: dict) -> list[str]:
    """Coherencia entre marca, plataforma y modo (con los datos ya combinados)."""
    errors = []
    mode, platform, vendor = merged.get("connection_mode") or "ninguno", merged.get("platform"), merged.get("vendor")
    if platform and PLATFORM_VENDOR.get(platform) != vendor:
        errors.append(f"La plataforma {platform} no corresponde a un equipo {vendor}")
    if mode != "ninguno" and not platform:
        errors.append("Elija la plataforma del equipo para poder conectarse")
    if mode == "consola":
        if vendor != "Cisco":
            errors.append("La conexión por consola solo está disponible para Cisco")
        if not merged.get("console_port"):
            errors.append("El modo consola necesita el puerto (ej. COM3)")
    return errors


def _row(row) -> dict:
    return dict(row) if row else None


@bp.get("")
def list_devices():
    # Fase 8.4: cuántas interfaces tiene registradas cada equipo
    rows = get_db().execute(
        "SELECT d.*, (SELECT COUNT(*) FROM interfaces i WHERE i.device_id = d.id) AS interface_count "
        "FROM devices d ORDER BY d.name").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/<int:device_id>")
def get_device(device_id):
    row = get_db().execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if row is None:
        return jsonify(error="Equipo no encontrado"), 404
    return jsonify(dict(row))


@bp.post("")
def create_device():
    data, errors = validate(request.get_json(silent=True) or {})
    if not errors:
        errors = check_connection(data)
    if errors:
        return jsonify(errors=errors), 400
    data.setdefault("status", "desconocido")
    data.setdefault("authorized", 1)
    data.setdefault("is_simulated", 1)   # en el MVP todo lo que se registra es de prueba
    data["created_at"] = data["updated_at"] = now_iso()

    conn = get_db()
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    try:
        cur = conn.execute(f"INSERT INTO devices ({cols}) VALUES ({marks})", tuple(data.values()))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify(errors=["Ya existe un equipo con ese nombre o esa IP"]), 409

    audit(conn, _operator(), "device.create", "devices", cur.lastrowid,
          f"{data['name']} {data['ip']} {data['vendor']}")
    return jsonify(_row(conn.execute("SELECT * FROM devices WHERE id = ?",
                                     (cur.lastrowid,)).fetchone())), 201


@bp.put("/<int:device_id>")
def update_device(device_id):
    conn = get_db()
    current = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if current is None:
        return jsonify(error="Equipo no encontrado"), 404

    data, errors = validate(request.get_json(silent=True) or {}, partial=True)
    if not errors:
        errors = check_connection({**dict(current), **data})
    if errors:
        return jsonify(errors=errors), 400
    if not data:
        return jsonify(errors=["No se enviaron campos para actualizar"]), 400

    data["updated_at"] = now_iso()   # la fecha de actualización cambia sola
    sets = ", ".join(f"{k} = ?" for k in data)   # los nombres vienen de validate(), no del usuario
    try:
        conn.execute(f"UPDATE devices SET {sets} WHERE id = ?", (*data.values(), device_id))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify(errors=["Ya existe un equipo con ese nombre o esa IP"]), 409

    changed = ", ".join(f"{k}={v}" for k, v in data.items() if k != "updated_at")
    audit(conn, _operator(), "device.update", "devices", device_id, changed)
    return jsonify(_row(conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()))


@bp.delete("/<int:device_id>")
def delete_device(device_id):
    conn = get_db()
    row = conn.execute("SELECT name, ip FROM devices WHERE id = ?", (device_id,)).fetchone()
    if row is None:
        return jsonify(error="Equipo no encontrado"), 404
    # Los eventos del equipo NO se borran: quedan con device_id = NULL
    # (ON DELETE SET NULL en schema.sql) para conservar la trazabilidad.
    # Sus interfaces SÍ se borran (ON DELETE CASCADE, Fase 8.4).
    n_ifaces = conn.execute("SELECT COUNT(*) FROM interfaces WHERE device_id = ?", (device_id,)).fetchone()[0]
    conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    conn.commit()
    audit(conn, _operator(), "device.delete", "devices", device_id,
          f"{row['name']} {row['ip']} interfaces={n_ifaces}")
    return jsonify(deleted=device_id)
