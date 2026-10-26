"""
Fase 10.4: INDICADORES DE OPERACIÓN del NOC (MTTA, MTTR, SLA y cambios).

    GET /api/metrics?dias=7|30|90|0&origen=todos|reales|simulados

DEFINICIONES (sobre los incidentes, con las fechas que se guardan desde la Fase 7)
    MTTA (Mean Time To Acknowledge) = tiempo medio hasta que ALGUIEN atiende el
         incidente: la primera de asignado, en progreso o cerrado.
    MTTR (Mean Time To Resolve)     = tiempo medio desde que se abre hasta que se
         cierra (solo incidentes cerrados).
    Se muestran el PROMEDIO y la MEDIANA: un solo incidente olvidado un fin de
    semana sube mucho el promedio; la mediana dice qué es lo "normal".

OBJETIVOS (SLA internos del NOC, por severidad)   atender     resolver
    0-1 Emergency / Alert                          15 min      4 h
    2   Critical                                   30 min      8 h
    3   Error                                       1 h       24 h
    4-7 (incidentes manuales)                       4 h       72 h
    Cumplimiento = % de incidentes atendidos / resueltos dentro del objetivo.
    Un incidente ABIERTO que ya pasó su objetivo aparece como VENCIDO.

CAMBIOS (Fase 10.2-10.3): cuántos, cómo terminaron, tasa de éxito, rollbacks y
    tiempo medio de aprobación (envío -> aprobado).
"""
import statistics
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from .db import get_db
from .timeutil import local_tz

bp = Blueprint("metrics", __name__, url_prefix="/api/metrics")

PERIODS = (7, 30, 90, 0)          # 0 = todo el historial
ORIGINS = ("todos", "reales", "simulados")
SEV_GROUPS = [((0, 1), "0-1 Emergency/Alert", 15 * 60, 4 * 3600),
              ((2,), "2 Critical", 30 * 60, 8 * 3600),
              ((3,), "3 Error", 3600, 24 * 3600),
              ((4, 5, 6, 7), "4-7 Otros", 4 * 3600, 72 * 3600)]
MAX_TREND_DAYS = 30


def _parse(iso):
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if iso else None


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def human(seconds) -> str:
    if seconds is None:
        return "—"
    s = int(round(seconds))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    if s < 86400 * 2:                       # hasta 48 h se muestra en horas (24 h, 1 h 30 min)
        return f"{s // 3600} h" + (f" {s % 3600 // 60} min" if s % 3600 >= 60 else "")
    if s % 86400 == 0:
        return f"{s // 86400} d"
    return f"{s // 86400} d {s % 86400 // 3600} h"


def target_for(severity: int) -> tuple[str, int, int]:
    for sevs, label, ack, res in SEV_GROUPS:
        if severity in sevs:
            return label, ack, res
    return SEV_GROUPS[-1][1:]


def ack_time(row):
    """Primer momento en que alguien atendió el incidente (o None si nadie lo ha hecho)."""
    times = [t for t in (_parse(row["assigned_at"]), _parse(row["started_at"]), _parse(row["closed_at"])) if t]
    return min(times) if times else None


def _stats(values) -> dict:
    if not values:
        return {"n": 0, "mean_s": None, "median_s": None, "mean": "—", "median": "—"}
    mean, median = statistics.fmean(values), statistics.median(values)
    return {"n": len(values), "mean_s": round(mean), "median_s": round(median),
            "mean": human(mean), "median": human(median)}


def _pct(ok, total):
    return round(100 * ok / total, 1) if total else None


def compute(conn, days: int = 30, origin: str = "todos", now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    where, params = [], []
    if days:
        where.append("created_at >= ?")
        params.append(_iso(now - timedelta(days=days)))
    if origin == "reales":
        where.append("is_simulated = 0")
    elif origin == "simulados":
        where.append("is_simulated = 1")
    sql = "SELECT i.*, d.name AS device_name FROM incidents i LEFT JOIN devices d ON d.id = i.device_id"
    if where:
        sql += " WHERE " + " AND ".join("i." + w for w in where)
    rows = conn.execute(sql, params).fetchall()

    acks, ress = [], []
    groups = {label: {"label": label, "target_ack": human(a), "target_res": human(r), "total": 0, "open": 0,
                      "ack": [], "res": [], "ack_ok": 0, "res_ok": 0, "ack_n": 0, "res_n": 0}
              for _, label, a, r in SEV_GROUPS}
    devices, overdue = {}, []
    for r in rows:
        created = _parse(r["created_at"])
        label, t_ack, t_res = target_for(r["severity"])
        g = groups[label]
        g["total"] += 1
        a = ack_time(r)
        closed = _parse(r["closed_at"]) if r["status"] == "cerrado" else None
        if a:
            secs = max(0.0, (a - created).total_seconds())
            acks.append(secs)
            g["ack"].append(secs)
            g["ack_n"] += 1
            g["ack_ok"] += secs <= t_ack
        if closed:
            secs = max(0.0, (closed - created).total_seconds())
            ress.append(secs)
            g["res"].append(secs)
            g["res_n"] += 1
            g["res_ok"] += secs <= t_res
        else:
            g["open"] += 1
            age = (now - created).total_seconds()
            late = []
            if a is None and age > t_ack:
                late.append(f"sin atender hace {human(age)} (objetivo {human(t_ack)})")
            if age > t_res:
                late.append(f"abierto hace {human(age)} (objetivo de solución {human(t_res)})")
            if late:
                overdue.append({"id": r["id"], "title": r["title"], "severity": r["severity"],
                                "device": r["device_name"] or "—", "status": r["status"],
                                "age_s": round(age), "detail": " · ".join(late),
                                "is_simulated": r["is_simulated"]})
        dev = devices.setdefault(r["device_name"] or "(sin equipo)", {"device": r["device_name"] or "(sin equipo)",
                                                                      "total": 0, "open": 0, "res": []})
        dev["total"] += 1
        if closed:
            dev["res"].append((closed - created).total_seconds())
        else:
            dev["open"] += 1

    by_severity = []
    for _, label, _a, _r in SEV_GROUPS:
        g = groups[label]
        by_severity.append({"label": label, "target_ack": g["target_ack"], "target_res": g["target_res"],
                            "total": g["total"], "open": g["open"], "mtta": _stats(g["ack"]), "mttr": _stats(g["res"]),
                            "ack_sla_pct": _pct(g["ack_ok"], g["ack_n"]), "res_sla_pct": _pct(g["res_ok"], g["res_n"])})
    total_ack_ok = sum(groups[l]["ack_ok"] for l in groups)
    total_res_ok = sum(groups[l]["res_ok"] for l in groups)
    by_device = sorted(({"device": d["device"], "total": d["total"], "open": d["open"], "mttr": _stats(d["res"])}
                        for d in devices.values()), key=lambda x: (-x["total"], x["device"]))[:10]
    overdue.sort(key=lambda x: (x["severity"], -x["age_s"]))

    # --- Tendencia diaria (hora de Colombia) ---------------------------------------
    n_days = min(days or MAX_TREND_DAYS, MAX_TREND_DAYS)
    local = local_tz()
    today = now.astimezone(local).date()
    trend = {(today - timedelta(days=i)).isoformat(): {"created": 0, "closed": 0} for i in range(n_days - 1, -1, -1)}
    for r in rows:
        day = _parse(r["created_at"]).astimezone(local).date().isoformat()
        if day in trend:
            trend[day]["created"] += 1
        if r["status"] == "cerrado" and r["closed_at"]:
            cday = _parse(r["closed_at"]).astimezone(local).date().isoformat()
            if cday in trend:
                trend[cday]["closed"] += 1

    return {"days": days, "origin": origin, "generated_at": _iso(now), "incidents": len(rows),
            "mtta": _stats(acks), "mttr": _stats(ress),
            "ack_sla_pct": _pct(total_ack_ok, len(acks)), "res_sla_pct": _pct(total_res_ok, len(ress)),
            "open": sum(1 for r in rows if r["status"] != "cerrado"), "overdue": overdue[:20],
            "overdue_count": len(overdue), "by_severity": by_severity, "by_device": by_device,
            "trend": [{"day": k, **v} for k, v in trend.items()],
            "changes": change_metrics(conn, days, now)}


def change_metrics(conn, days, now) -> dict:
    params, where = [], ""
    if days:
        where, params = " WHERE created_at >= ?", [_iso(now - timedelta(days=days))]
    rows = conn.execute("SELECT status, submitted_at, approved_at, risk_level FROM change_requests" + where,
                        params).fetchall()
    by_status = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    finished = sum(by_status.get(s, 0) for s in ("ejecutado", "fallido", "revertido"))
    approval = [(_parse(r["approved_at"]) - _parse(r["submitted_at"])).total_seconds()
                for r in rows if r["approved_at"] and r["submitted_at"]]
    by_risk = {lvl: sum(1 for r in rows if r["risk_level"] == lvl) for lvl in ("bajo", "medio", "alto")}
    return {"total": len(rows), "by_status": by_status, "by_risk": by_risk, "finished": finished,
            "success_pct": _pct(by_status.get("ejecutado", 0), finished),
            "rollbacks": by_status.get("revertido", 0), "failed": by_status.get("fallido", 0),
            "approval_time": _stats(approval)}


@bp.get("")
def metrics():
    errors = []
    try:
        days = int(request.args.get("dias", "30"))
        if days not in PERIODS:
            raise ValueError
    except ValueError:
        errors.append("dias: use 7, 30, 90 o 0 (todo)")
        days = 30
    origin = request.args.get("origen", "todos")
    if origin not in ORIGINS:
        errors.append("origen: use todos, reales o simulados")
    if errors:
        return jsonify(errors=errors), 400
    return jsonify(compute(get_db(), days, origin))
