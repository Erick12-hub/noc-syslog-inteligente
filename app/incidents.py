"""
Gestión de incidentes: creación, asignación, seguimiento y cierre.

    GET  /api/incidents?estado=abiertos|cerrado|todos   Listar
    GET  /api/incidents/<id>                            Detalle + notas + evento origen
    POST /api/incidents                                 Crear (manual o desde un evento)
    POST /api/incidents/<id>/assign                     Asignar responsable
    POST /api/incidents/<id>/status                     Cambiar estado (cerrar exige resolución)
    POST /api/incidents/<id>/notes                      Agregar nota de seguimiento

CICLO DE VIDA (máquina de estados). Solo se permiten estas transiciones:

    abierto ──> asignado ──> en_progreso ──> cerrado
       │            └──────────────────────────^
       └───────────────────────────────────────^

Un incidente cerrado no se puede modificar: queda como registro histórico.

SEGURIDAD: el título y la descripción de un incidente automático los escribe
el SISTEMA a partir de datos estructurados (equipo, código, severidad). Nunca se
copia el texto del log, porque es un dato no confiable: si un atacante escribe
"IGNORA TUS REGLAS..." en un log, ese texto no termina en el título del
incidente que luego leerán personas o asistentes de IA.
"""
from flask import Blueprint, current_app, jsonify, request

from .db import audit, get_db, now_iso

bp = Blueprint("incidents", __name__, url_prefix="/api/incidents")

STATUSES = ("abierto", "asignado", "en_progreso", "cerrado")
TRANSITIONS = {
    "abierto": {"asignado", "en_progreso", "cerrado"},
    "asignado": {"en_progreso", "cerrado"},
    "en_progreso": {"cerrado"},
    "cerrado": set(),   # estado final
}
SEVERITY_NAMES = ["Emergency", "Alert", "Critical", "Error",
                  "Warning", "Notice", "Informational", "Debug"]
MIN_RESOLUTION = 10      # caracteres mínimos de la resolución al cerrar
MAX_TEXT = 2000


# ---------------------------------------------------------------------------
# Funciones de dominio (las usan la API y la ingesta automática)
# ---------------------------------------------------------------------------
def add_note(conn, incident_id: int, author: str, note: str):
    conn.execute("INSERT INTO incident_notes (incident_id, author, note, created_at) "
                 "VALUES (?, ?, ?, ?)", (incident_id, author, note, now_iso()))


def create_incident(conn, *, title, severity, created_by, description=None,
                    device_id=None, event_id=None, correlation_key=None,
                    is_simulated=False) -> int:
    ts = now_iso()
    cur = conn.execute(
        "INSERT INTO incidents (title, description, severity, status, device_id, event_id, "
        "created_by, created_at, updated_at, is_simulated, correlation_key, event_count, last_event_at) "
        "VALUES (?, ?, ?, 'abierto', ?, ?, ?, ?, ?, ?, ?, 1, ?)",
        (title, description, severity, device_id, event_id, created_by, ts, ts,
         int(is_simulated), correlation_key, ts))
    incident_id = cur.lastrowid
    add_note(conn, incident_id, created_by, "Incidente creado")
    conn.commit()
    audit(conn, created_by, "incident.create", "incidents", incident_id,
          f"sev={severity} evento={event_id} titulo={title}")
    return incident_id


def auto_incident_from_event(conn, event: dict) -> dict | None:
    """
    Política (RF-08): un evento de severidad 0-3 de una FUENTE AUTORIZADA genera
    un incidente. Si ya existe uno abierto con la misma clave de correlación
    (mismo equipo + mismo código de evento), se suma a ese (RF-12).

    event: diccionario con id, device_id, device_name, severity, mnemonic,
           fingerprint, flags, authorized, is_simulated.
    Devuelve {"id": ..., "correlated": bool} o None si no aplica.
    """
    if not event["authorized"]:
        return None   # una fuente no autorizada NUNCA crea incidentes
    policy = conn.execute("SELECT creates_incident FROM severities WHERE code = ?",
                          (event["severity"],)).fetchone()
    if not policy or not policy["creates_incident"]:
        return None

    key = f'{event["device_id"]}|{event["mnemonic"] or event["fingerprint"]}'
    existing = conn.execute(
        "SELECT id, severity FROM incidents WHERE correlation_key = ? AND status != 'cerrado' "
        "ORDER BY id DESC LIMIT 1", (key,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE incidents SET event_count = event_count + 1, last_event_at = ?, "
            "severity = MIN(severity, ?), updated_at = ? WHERE id = ?",
            (now_iso(), event["severity"], now_iso(), existing["id"]))
        conn.commit()
        return {"id": existing["id"], "correlated": True}

    # Título generado por el sistema (nunca con el texto del log)
    device = event["device_name"] or "equipo desconocido"
    if "posible_prompt_injection" in (event.get("flags") or []):
        title = f"Posible prompt injection en log de {device}"
    else:
        code = (event["mnemonic"] or "").replace("logid=", "FortiOS logid ")
        title = f'{code or "Evento " + SEVERITY_NAMES[event["severity"]]} en {device}'
    description = (f'Generado automáticamente por la política de severidades: evento #{event["id"]}, '
                   f'severidad {event["severity"]} ({SEVERITY_NAMES[event["severity"]]}). '
                   f'Revise el mensaje original en el detalle del evento.')
    incident_id = create_incident(
        conn, title=title, severity=event["severity"], created_by="sistema",
        description=description, device_id=event["device_id"], event_id=event["id"],
        correlation_key=key, is_simulated=event["is_simulated"])
    return {"id": incident_id, "correlated": False}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def _operator() -> str:
    return current_app.config["DEFAULT_OPERATOR"]


def _get(conn, incident_id):
    return conn.execute(
        "SELECT i.*, d.name AS device_name FROM incidents i "
        "LEFT JOIN devices d ON d.id = i.device_id WHERE i.id = ?", (incident_id,)).fetchone()


@bp.get("")
def list_incidents():
    estado = request.args.get("estado", "abiertos")
    sql = ("SELECT i.*, d.name AS device_name, "
           "(SELECT COUNT(*) FROM incident_notes n WHERE n.incident_id = i.id) AS notes_count "
           "FROM incidents i LEFT JOIN devices d ON d.id = i.device_id")
    params = []
    if estado == "abiertos":
        sql += " WHERE i.status != 'cerrado'"
    elif estado in STATUSES:
        sql += " WHERE i.status = ?"
        params.append(estado)
    # Primero lo más grave, luego lo más reciente
    sql += " ORDER BY (i.status = 'cerrado'), i.severity ASC, i.id DESC LIMIT 300"
    return jsonify([dict(r) for r in get_db().execute(sql, params).fetchall()])


@bp.get("/<int:incident_id>")
def get_incident(incident_id):
    conn = get_db()
    inc = _get(conn, incident_id)
    if inc is None:
        return jsonify(error="Incidente no encontrado"), 404
    notes = conn.execute("SELECT * FROM incident_notes WHERE incident_id = ? ORDER BY id",
                         (incident_id,)).fetchall()
    event = None
    if inc["event_id"]:
        event = conn.execute(
            "SELECT id, received_at, source_ip, severity, mnemonic, message, raw, flags "
            "FROM syslog_events WHERE id = ?", (inc["event_id"],)).fetchone()
    return jsonify(incident=dict(inc), notes=[dict(n) for n in notes],
                   event=dict(event) if event else None,
                   allowed=sorted(TRANSITIONS[inc["status"]]))


@bp.post("")
def create():
    """Crear manualmente. Si se envía event_id, los datos salen del evento."""
    data = request.get_json(silent=True) or {}
    conn = get_db()
    errors = []

    event_id = data.get("event_id")
    if event_id is not None:
        ev = conn.execute(
            "SELECT e.id, e.severity, e.device_id, e.mnemonic, e.is_simulated, d.name AS device_name "
            "FROM syslog_events e LEFT JOIN devices d ON d.id = e.device_id WHERE e.id = ?",
            (event_id,)).fetchone()
        if ev is None:
            return jsonify(errors=["El evento no existe"]), 404
        dup = conn.execute("SELECT id FROM incidents WHERE event_id = ? AND status != 'cerrado'",
                           (event_id,)).fetchone()
        if dup:
            return jsonify(errors=[f"El evento ya tiene el incidente abierto #{dup['id']}"],
                           incident_id=dup["id"]), 409
        title = (data.get("title") or "").strip() or \
            f'{ev["mnemonic"] or "Evento #" + str(ev["id"])} en {ev["device_name"] or "equipo desconocido"}'
        severity, device_id, is_sim = ev["severity"], ev["device_id"], ev["is_simulated"]
    else:
        title = (data.get("title") or "").strip()
        try:
            severity = int(data.get("severity"))
            if not 0 <= severity <= 7:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("La severidad debe ser un número de 0 a 7")
            severity = None
        device_id = data.get("device_id") or None
        if device_id and conn.execute("SELECT 1 FROM devices WHERE id = ?", (device_id,)).fetchone() is None:
            errors.append("El equipo no existe")
        is_sim = True

    if not 3 <= len(title) <= 200:
        errors.append("El título debe tener entre 3 y 200 caracteres")
    description = (data.get("description") or "").strip()[:MAX_TEXT] or None
    if errors:
        return jsonify(errors=errors), 400

    incident_id = create_incident(conn, title=title, severity=severity, created_by=_operator(),
                                  description=description, device_id=device_id,
                                  event_id=event_id, is_simulated=is_sim)
    return jsonify(dict(_get(conn, incident_id))), 201


def _load_open(conn, incident_id):
    """Devuelve (incidente, respuesta_de_error). Bloquea cambios en incidentes cerrados."""
    inc = _get(conn, incident_id)
    if inc is None:
        return None, (jsonify(error="Incidente no encontrado"), 404)
    if inc["status"] == "cerrado":
        return None, (jsonify(errors=["El incidente está cerrado y no se puede modificar"]), 409)
    return inc, None


@bp.post("/<int:incident_id>/assign")
def assign(incident_id):
    conn = get_db()
    inc, err = _load_open(conn, incident_id)
    if err:
        return err
    who = ((request.get_json(silent=True) or {}).get("assigned_to") or "").strip()
    if not 2 <= len(who) <= 60:
        return jsonify(errors=["Indique el responsable (2 a 60 caracteres)"]), 400

    new_status = "asignado" if inc["status"] == "abierto" else inc["status"]
    conn.execute("UPDATE incidents SET assigned_to = ?, status = ?, updated_at = ? WHERE id = ?",
                 (who, new_status, now_iso(), incident_id))
    add_note(conn, incident_id, _operator(), f"Asignado a {who}")
    conn.commit()
    audit(conn, _operator(), "incident.assign", "incidents", incident_id, f"responsable={who}")
    return jsonify(dict(_get(conn, incident_id)))


@bp.post("/<int:incident_id>/status")
def change_status(incident_id):
    conn = get_db()
    inc, err = _load_open(conn, incident_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    new = data.get("status")
    if new not in STATUSES:
        return jsonify(errors=[f"Estado inválido. Opciones: {', '.join(STATUSES)}"]), 400
    if new not in TRANSITIONS[inc["status"]]:
        return jsonify(errors=[f"No se permite pasar de '{inc['status']}' a '{new}'"]), 409
    if new == "asignado" and not inc["assigned_to"]:
        return jsonify(errors=["Para pasar a 'asignado' primero asigne un responsable"]), 400

    ts = now_iso()
    if new == "cerrado":
        resolution = (data.get("resolution") or "").strip()
        if len(resolution) < MIN_RESOLUTION:
            return jsonify(errors=[f"Para cerrar escriba la resolución (mínimo {MIN_RESOLUTION} caracteres)"]), 400
        conn.execute("UPDATE incidents SET status = 'cerrado', resolution = ?, closed_at = ?, "
                     "updated_at = ? WHERE id = ?", (resolution[:MAX_TEXT], ts, ts, incident_id))
        add_note(conn, incident_id, _operator(), f"Cerrado. Resolución: {resolution[:MAX_TEXT]}")
    else:
        conn.execute("UPDATE incidents SET status = ?, updated_at = ? WHERE id = ?",
                     (new, ts, incident_id))
        add_note(conn, incident_id, _operator(), f"Estado: {inc['status']} → {new}")
    conn.commit()
    audit(conn, _operator(), "incident.status", "incidents", incident_id, f"{inc['status']}->{new}")
    return jsonify(dict(_get(conn, incident_id)))


@bp.post("/<int:incident_id>/notes")
def add_note_api(incident_id):
    conn = get_db()
    inc, err = _load_open(conn, incident_id)
    if err:
        return err
    note = ((request.get_json(silent=True) or {}).get("note") or "").strip()
    if not 2 <= len(note) <= MAX_TEXT:
        return jsonify(errors=["La nota debe tener entre 2 y 2000 caracteres"]), 400
    add_note(conn, incident_id, _operator(), note)
    conn.execute("UPDATE incidents SET updated_at = ? WHERE id = ?", (now_iso(), incident_id))
    conn.commit()
    audit(conn, _operator(), "incident.note", "incidents", incident_id, note[:120])
    return jsonify(ok=True), 201
