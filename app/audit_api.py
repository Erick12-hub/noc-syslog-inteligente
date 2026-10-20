"""
Consulta de la auditoría (RF-14): quién hizo qué, cuándo y con qué resultado.

    GET /api/audit?actor=asistente_ia&result=bloqueado&q=console&limit=200
    GET /api/audit/verify      Verifica la cadena de integridad (Fase 8.2)

Solo LECTURA: la aplicación no tiene ninguna ruta para modificar o borrar
registros de auditoría (si se pudieran borrar, un atacante borraría sus huellas).
"""
from flask import Blueprint, jsonify, request

from .auth import actor
from .db import audit, get_db, verify_audit_chain
from .validation import ParamValidator

RESULTS = ("ok", "alerta", "bloqueado", "error")

bp = Blueprint("audit", __name__, url_prefix="/api/audit")


@bp.get("")
def list_audit():
    # Fase 7.3: parámetros validados; un valor inválido responde 400
    v = ParamValidator(request.args)
    actor = v.text("actor", 60, "Actor")
    result = v.choice("result", RESULTS, "Resultado")
    q = v.text("q", 100, "Texto de búsqueda")
    limit = v.integer("limit", 1, 1000, "Límite", default=200)
    if v.errors:
        return jsonify(errors=v.errors), 400
    where, params = [], []
    if actor:
        where.append("actor = ?")
        params.append(actor)
    if result:
        where.append("result = ?")
        params.append(result)
    if q:
        where.append("(action LIKE ? OR detail LIKE ?)")
        params += [f"%{q}%"] * 2
    sql = "SELECT * FROM audit_log" + (" WHERE " + " AND ".join(where) if where else "")
    rows = get_db().execute(sql + " ORDER BY id DESC LIMIT ?", (*params, limit)).fetchall()
    actors = [r[0] for r in get_db().execute("SELECT DISTINCT actor FROM audit_log ORDER BY actor")]
    return jsonify(rows=[dict(r) for r in rows], actors=actors)


@bp.get("/verify")
def verify():
    """
    Fase 8.2: recalcula toda la cadena de hashes. Primero se verifica y DESPUÉS
    se registra la verificación (si no, el propio registro entraría al cálculo).
    """
    conn = get_db()
    report = verify_audit_chain(conn)
    if report["ok"]:
        audit(conn, actor(), "audit.verify", "audit_log", report["last_id"],
              f"cadena integra: {report['total']} registros, ultimo hash {report['last_hash'][:16]}")
    else:
        audit(conn, actor(), "audit.verify", "audit_log", report["broken_at"],
              f"CADENA ROTA en el registro {report['broken_at']}: {report['reason']}", "alerta")
    return jsonify(report)
