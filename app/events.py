"""
API de eventos Syslog.

    GET  /api/events          Listar con filtros
    GET  /api/events/<id>     Detalle de un evento (incluye el mensaje crudo)
    POST /api/events/import   Importar un archivo .log de un equipo

Filtros de GET /api/events (todos opcionales y combinables):
    desde=AAAA-MM-DD   hasta=AAAA-MM-DD  (hora de Colombia; nunca posteriores a hoy)   vendor=Cisco   device_id=3
    severity=3         sev_max=3 (de 0 hasta 3)        flag=fuente_no_autorizada
    interface=Gi0/1    port=22 (puerto de origen O de destino)      [Fase 7]
    limit=100 (máx. 500)

Fase 7: los filtros nuevos (interface, port) se VALIDAN. Si el valor no es
válido se responde 400 con la lista de errores, en vez de ignorarlo en silencio.
"""
from flask import Blueprint, current_app, jsonify, request

from .db import get_db
from .ingest import import_lines
from .syslog_parser import is_valid_interface, is_valid_port, normalize_interface
from .timeutil import local_today, validate_date_range

bp = Blueprint("events", __name__, url_prefix="/api/events")


def _int(value, default=None, lo=None, hi=None):
    """Convierte a entero dentro de un rango; si no es válido devuelve default."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if (lo is not None and n < lo) or (hi is not None and n > hi):
        return default
    return n


@bp.get("")
def list_events():
    a = request.args
    where, params, errors = [], [], []

    # Cada filtro agrega una condición con parámetro "?": nunca se pega texto
    # del usuario dentro del SQL (prevención de inyección SQL).
    # --- Fase 7: rango de fechas --------------------------------------------
    # Se valida (formato, sin fechas futuras, desde <= hasta) y cada día se
    # convierte de hora de Colombia a UTC, que es como se guarda received_at.
    date_errors, bounds = validate_date_range(a.get("desde"), a.get("hasta"))
    errors += date_errors
    if "desde_utc" in bounds:
        where.append("e.received_at >= ?")
        params.append(bounds["desde_utc"])
    if "hasta_utc" in bounds:
        where.append("e.received_at <= ?")
        params.append(bounds["hasta_utc"])
    if a.get("vendor"):
        where.append("e.vendor = ?")
        params.append(a["vendor"])
    if _int(a.get("device_id")) is not None:
        where.append("e.device_id = ?")
        params.append(_int(a["device_id"]))
    if _int(a.get("severity"), lo=0, hi=7) is not None:
        where.append("e.severity = ?")
        params.append(_int(a["severity"]))
    if _int(a.get("sev_max"), lo=0, hi=7) is not None:
        where.append("e.severity <= ?")
        params.append(_int(a["sev_max"]))
    if a.get("flag"):
        where.append("(',' || e.flags || ',') LIKE ?")
        params.append(f"%,{a['flag']},%")

    # --- Fase 7: interfaz y puerto -----------------------------------------
    if a.get("interface"):
        iface = a["interface"].strip()
        if not is_valid_interface(iface):
            errors.append("Interfaz inválida: use letras, números y / . - _ : (ej. Gi0/1, port1)")
        else:
            # Se compara con el nombre normalizado: 'Gi0/1' encuentra 'GigabitEthernet0/1'
            where.append("e.interface = ? COLLATE NOCASE")
            params.append(normalize_interface(iface))
    if a.get("port"):
        if not is_valid_port(a["port"]):
            errors.append("Puerto inválido: debe ser un número entre 1 y 65535")
        else:
            where.append("(e.src_port = ? OR e.dst_port = ?)")
            params += [int(a["port"])] * 2
    if errors:
        return jsonify(errors=errors), 400

    limit = _int(a.get("limit"), 100, 1, 500)
    sql = ("SELECT e.*, d.name AS device_name, s.name AS severity_name "
           "FROM syslog_events e "
           "LEFT JOIN devices d ON d.id = e.device_id "
           "JOIN severities s ON s.code = e.severity")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY e.id DESC LIMIT ?"
    rows = get_db().execute(sql, (*params, limit)).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/<int:event_id>")
def get_event(event_id):
    row = get_db().execute(
        "SELECT e.*, d.name AS device_name, s.name AS severity_name FROM syslog_events e "
        "LEFT JOIN devices d ON d.id = e.device_id JOIN severities s ON s.code = e.severity "
        "WHERE e.id = ?", (event_id,)).fetchone()
    if row is None:
        return jsonify(error="Evento no encontrado"), 404
    return jsonify(dict(row))


@bp.post("/import")
def import_file():
    """Recibe un archivo (multipart) y el id del equipo al que pertenece."""
    file = request.files.get("file")
    device_id = _int(request.form.get("device_id"))
    if file is None or not file.filename:
        return jsonify(errors=["Seleccione un archivo .log o .txt"]), 400
    if device_id is None:
        return jsonify(errors=["Seleccione el equipo de origen"]), 400

    conn = get_db()
    device = conn.execute("SELECT ip FROM devices WHERE id = ?", (device_id,)).fetchone()
    if device is None:
        return jsonify(errors=["Equipo no encontrado"]), 404

    # errors="replace": un byte inválido no rompe la importación
    text = file.read().decode("utf-8", errors="replace")
    stats = import_lines(conn, text.splitlines(), device["ip"],
                         current_app.config["DEFAULT_OPERATOR"], file.filename)
    return jsonify(stats)


@bp.get("/today")
def today():
    """Fase 7: fecha de HOY en Colombia según el servidor (la interfaz la usa como máximo del filtro)."""
    return jsonify(today=local_today().isoformat())
