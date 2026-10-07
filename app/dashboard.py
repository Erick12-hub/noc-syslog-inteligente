"""
API del dashboard: resumen del estado de la red en una sola consulta.

    GET /api/dashboard

Devuelve indicadores de las últimas 24 horas, equipos por estado, eventos por
severidad y por hora, eventos críticos recientes e incidentes abiertos.
La página /  (dashboard.html) la consulta cada 15 segundos.
"""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify

from .db import get_db

bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")

CRITICAL_MAX = 3   # severidades 0 a 3 = críticas (misma política de incidentes)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@bp.get("")
def summary():
    conn = get_db()
    now = datetime.now(timezone.utc)
    since = _iso(now - timedelta(hours=24))

    # --- Equipos ----------------------------------------------------------
    by_status = {r["status"]: r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM devices GROUP BY status")}
    devices_total = sum(by_status.values())
    authorized = conn.execute("SELECT COUNT(*) FROM devices WHERE authorized = 1").fetchone()[0]

    # --- Eventos 24 h -----------------------------------------------------
    ev = conn.execute(
        "SELECT COUNT(*) AS eventos, COALESCE(SUM(dup_count), 0) AS mensajes, "
        "SUM(severity <= ?) AS criticos, "
        "SUM(authorized_source = 0) AS no_autorizados, "
        "SUM((',' || COALESCE(flags,'') || ',') LIKE '%,posible_prompt_injection,%') AS inyeccion "
        "FROM syslog_events WHERE received_at >= ?", (CRITICAL_MAX, since)).fetchone()

    by_severity = [0] * 8
    for r in conn.execute("SELECT severity, COUNT(*) AS n FROM syslog_events "
                          "WHERE received_at >= ? GROUP BY severity", (since,)):
        by_severity[r["severity"]] = r["n"]

    # Eventos por hora (24 barras). Se agrupan por los 13 primeros caracteres
    # de la fecha ISO: "2026-10-06T18" = la hora 18 UTC de ese día.
    counts = {r["h"]: (r["n"], r["c"]) for r in conn.execute(
        "SELECT substr(received_at, 1, 13) AS h, COUNT(*) AS n, SUM(severity <= ?) AS c "
        "FROM syslog_events WHERE received_at >= ? GROUP BY h", (CRITICAL_MAX, since))}
    by_hour = []
    for i in range(23, -1, -1):
        h = (now - timedelta(hours=i)).strftime("%Y-%m-%dT%H")
        n, c = counts.get(h, (0, 0))
        by_hour.append({"hour": h + ":00:00Z", "total": n, "critical": c or 0})

    recent_critical = conn.execute(
        "SELECT e.id, e.received_at, e.severity, e.vendor, e.mnemonic, e.message, e.flags, "
        "e.dup_count, e.source_ip, d.name AS device_name FROM syslog_events e "
        "LEFT JOIN devices d ON d.id = e.device_id WHERE e.severity <= ? "
        "ORDER BY e.id DESC LIMIT 8", (CRITICAL_MAX,)).fetchall()

    # --- Incidentes -------------------------------------------------------
    inc_status = {r["status"]: r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM incidents GROUP BY status")}
    open_incidents = conn.execute(
        "SELECT i.id, i.title, i.severity, i.status, i.assigned_to, i.event_count, "
        "i.created_at, i.last_event_at, d.name AS device_name FROM incidents i "
        "LEFT JOIN devices d ON d.id = i.device_id WHERE i.status != 'cerrado' "
        "ORDER BY i.severity ASC, i.id DESC LIMIT 8").fetchall()
    last = conn.execute("SELECT MAX(received_at) FROM syslog_events").fetchone()[0]

    return jsonify(
        generated_at=_iso(now),
        devices={"total": devices_total, "authorized": authorized, "by_status": by_status},
        events_24h={"eventos": ev["eventos"], "mensajes": ev["mensajes"],
                    "criticos": ev["criticos"] or 0, "no_autorizados": ev["no_autorizados"] or 0,
                    "inyeccion": ev["inyeccion"] or 0},
        by_severity=by_severity,
        by_hour=by_hour,
        recent_critical=[dict(r) for r in recent_critical],
        incidents={"open": sum(n for s, n in inc_status.items() if s != "cerrado"),
                   "by_status": inc_status},
        open_incidents=[dict(r) for r in open_incidents],
        last_event_at=last,
    )
