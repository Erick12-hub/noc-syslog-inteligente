"""
API de eventos Syslog.

    GET  /api/events          Listar con filtros
    GET  /api/events/<id>     Detalle de un evento (incluye el mensaje crudo)
    POST /api/events/import   Importar un archivo .log de un equipo

Filtros de GET /api/events (todos opcionales y combinables):
    desde=AAAA-MM-DD   hasta=AAAA-MM-DD  (hora de Colombia; nunca posteriores a hoy)   vendor=Cisco   device_id=3
    severity=3         sev_max=3 (de 0 hasta 3)        flag=fuente_no_autorizada
    interface=Gi0/1    port=22 (puerto de origen O de destino)      [Fase 7]
    limit=100 (máx. 500)   page=1 (Fase 7.4: paginación)

Fase 7.4: la respuesta sigue siendo una lista, y el total va en encabezados:
    X-Total-Count: 450   X-Page: 2   X-Per-Page: 100   X-Total-Pages: 5

Fase 7: TODOS los filtros se VALIDAN (app/validation.py). Si un valor no es
válido se responde 400 con la lista de errores, en vez de ignorarlo en silencio.
"""
from flask import Blueprint, current_app, jsonify, request

from .db import get_db
from .db import audit
from .ingest import check_import_vendor, import_lines
from .syslog_parser import is_valid_interface, is_valid_port, normalize_interface
from .timeutil import local_today, validate_date_range
from .validation import EVENT_VENDORS, KNOWN_FLAGS, ParamValidator

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
    v = ParamValidator(a)          # Fase 7.3: acumula los errores de todos los filtros
    errors = v.errors
    where, params = [], []

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
    # --- Fase 7.3: cada filtro se valida; ya no se ignoran en silencio -------
    vendor = v.choice("vendor", EVENT_VENDORS, "Marca")
    device_id = v.integer("device_id", 1, 10**9, "Equipo")
    severity = v.integer("severity", 0, 7, "Severidad")
    sev_max = v.integer("sev_max", 0, 7, "Severidad máxima")
    flag = v.choice("flag", KNOWN_FLAGS, "Marca de seguridad")
    limit = v.integer("limit", 1, 500, "Límite", default=100)
    page = v.integer("page", 1, 100000, "Página", default=1)
    if device_id is not None and get_db().execute(
            "SELECT 1 FROM devices WHERE id = ?", (device_id,)).fetchone() is None:
        errors.append(f"El equipo {device_id} no existe en el inventario")
    if vendor:
        where.append("e.vendor = ?")
        params.append(vendor)
    if device_id is not None:
        where.append("e.device_id = ?")
        params.append(device_id)
    if severity is not None:
        where.append("e.severity = ?")
        params.append(severity)
    if sev_max is not None:
        where.append("e.severity <= ?")
        params.append(sev_max)
    if flag:
        where.append("(',' || e.flags || ',') LIKE ?")
        params.append(f"%,{flag},%")

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

    # where solo contiene textos FIJOS con "?"; los valores van aparte en params
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    conn = get_db()
    # Fase 7.4: total de coincidencias (para "Página X de Y") y solo UNA página de filas
    total = conn.execute(f"SELECT COUNT(*) FROM syslog_events e{where_sql}", params).fetchone()[0]
    sql = ("SELECT e.*, d.name AS device_name, s.name AS severity_name "
           "FROM syslog_events e "
           "LEFT JOIN devices d ON d.id = e.device_id "
           "JOIN severities s ON s.code = e.severity"
           f"{where_sql} ORDER BY e.id DESC LIMIT ? OFFSET ?")
    rows = conn.execute(sql, (*params, limit, (page - 1) * limit)).fetchall()
    resp = jsonify([dict(r) for r in rows])
    resp.headers["X-Total-Count"] = str(total)
    resp.headers["X-Page"] = str(page)
    resp.headers["X-Per-Page"] = str(limit)
    resp.headers["X-Total-Pages"] = str(max(1, -(-total // limit)))   # división hacia arriba
    return resp


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
    device = conn.execute("SELECT ip, vendor FROM devices WHERE id = ?", (device_id,)).fetchone()
    if device is None:
        return jsonify(errors=["Equipo no encontrado"]), 404

    # errors="replace": un byte inválido no rompe la importación
    text = file.read().decode("utf-8", errors="replace")
    lines = text.splitlines()

    # Fase 7.3: coherencia equipo-marca. Un log de Cisco no se puede cargar
    # como si fuera de un FortiGate: se rechaza ANTES de guardar nada.
    problem = check_import_vendor(lines, device["vendor"])
    if problem:
        audit(conn, current_app.config["DEFAULT_OPERATOR"], "syslog.import_rechazado",
              "devices", device_id, f"archivo={file.filename} {problem}", "bloqueado")
        return jsonify(errors=[problem]), 409

    stats = import_lines(conn, lines, device["ip"],
                         current_app.config["DEFAULT_OPERATOR"], file.filename)
    return jsonify(stats)


@bp.get("/today")
def today():
    """Fase 7: fecha de HOY en Colombia según el servidor (la interfaz la usa como máximo del filtro)."""
    return jsonify(today=local_today().isoformat())
