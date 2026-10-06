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

from flask import Blueprint, current_app, jsonify, request

from .db import audit, get_db, now_iso

bp = Blueprint("devices", __name__, url_prefix="/api/devices")

VENDORS = ("Cisco", "Fortinet", "Huawei", "Otro")
STATUSES = ("activo", "alerta", "caido", "mantenimiento", "desconocido")
RE_NAME = re.compile(r"^[A-Za-z0-9._-]{2,64}$")   # sin espacios ni símbolos raros
TEXT_FIELDS = ("model", "version", "location")
MAX_TEXT = 100


def _operator() -> str:
    """Operador responsable (en el MVP no hay login; ver Corte 3)."""
    return current_app.config["DEFAULT_OPERATOR"]


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

    return clean, errors


def _row(row) -> dict:
    return dict(row) if row else None


@bp.get("")
def list_devices():
    rows = get_db().execute("SELECT * FROM devices ORDER BY name").fetchall()
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
    if conn.execute("SELECT 1 FROM devices WHERE id = ?", (device_id,)).fetchone() is None:
        return jsonify(error="Equipo no encontrado"), 404

    data, errors = validate(request.get_json(silent=True) or {}, partial=True)
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
    conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    conn.commit()
    audit(conn, _operator(), "device.delete", "devices", device_id, f"{row['name']} {row['ip']}")
    return jsonify(deleted=device_id)
