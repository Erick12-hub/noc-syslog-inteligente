"""
Consulta de la auditoría (RF-14): quién hizo qué, cuándo y con qué resultado.

    GET /api/audit?actor=asistente_ia&result=bloqueado&q=console&limit=200

Solo LECTURA: la aplicación no tiene ninguna ruta para modificar o borrar
registros de auditoría (si se pudieran borrar, un atacante borraría sus huellas).
"""
from flask import Blueprint, jsonify, request

from .db import get_db

bp = Blueprint("audit", __name__, url_prefix="/api/audit")


@bp.get("")
def list_audit():
    a = request.args
    where, params = [], []
    if a.get("actor"):
        where.append("actor = ?")
        params.append(a["actor"])
    if a.get("result"):
        where.append("result = ?")
        params.append(a["result"])
    if a.get("q"):
        where.append("(action LIKE ? OR detail LIKE ?)")
        params += [f"%{a['q']}%"] * 2
    try:
        limit = max(1, min(int(a.get("limit", 200)), 1000))
    except ValueError:
        limit = 200
    sql = "SELECT * FROM audit_log" + (" WHERE " + " AND ".join(where) if where else "")
    rows = get_db().execute(sql + " ORDER BY id DESC LIMIT ?", (*params, limit)).fetchall()
    actors = [r[0] for r in get_db().execute("SELECT DISTINCT actor FROM audit_log ORDER BY actor")]
    return jsonify(rows=[dict(r) for r in rows], actors=actors)
