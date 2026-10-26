"""
Pruebas de la Fase 10.4: indicadores de operación (MTTA, MTTR, SLA, vencidos y cambios).
Los incidentes se insertan con fechas fijas para que los resultados sean exactos.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.metrics import compute, human, target_for

NOW = datetime(2026, 10, 25, 20, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _inc(conn, sev, created_h_ago, ack_min=None, close_h=None, started_min=None, sim=1, device="SIM-CORE-RTR01"):
    created = NOW - timedelta(hours=created_h_ago)
    assigned = created + timedelta(minutes=ack_min) if ack_min is not None else None
    started = created + timedelta(minutes=started_min) if started_min is not None else None
    closed = created + timedelta(hours=close_h) if close_h is not None else None
    dev = conn.execute("SELECT id FROM devices WHERE name = ?", (device,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO incidents (title, severity, status, device_id, created_by, created_at, updated_at, is_simulated, "
        "event_count, last_event_at, assigned_at, started_at, closed_at) VALUES (?, ?, ?, ?, 'sistema', ?, ?, ?, 1, ?, ?, ?, ?)",
        (f"Prueba sev {sev}", sev, "cerrado" if closed else ("asignado" if assigned else "abierto"), dev,
         _iso(created), _iso(created), sim, _iso(created), _iso(assigned), _iso(started), _iso(closed)))
    conn.commit()


@pytest.fixture
def clean(conn):
    conn.execute("DELETE FROM incident_notes")
    conn.execute("DELETE FROM incidents")
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# 1. Cálculos
# ---------------------------------------------------------------------------
def test_mtta_y_mttr_promedio_y_mediana(clean):
    _inc(clean, 2, 48, ack_min=10, close_h=2)
    _inc(clean, 2, 40, ack_min=20, close_h=4)
    _inc(clean, 2, 30, ack_min=90, close_h=30)        # un caso lento sube el promedio, no la mediana
    m = compute(clean, 30, now=NOW)
    assert m["mtta"]["n"] == 3 and m["mtta"]["mean_s"] == 40 * 60 and m["mtta"]["median_s"] == 20 * 60
    assert m["mttr"]["mean_s"] == 12 * 3600 and m["mttr"]["median_s"] == 4 * 3600
    assert m["mtta"]["mean"] == "40 min" and m["mttr"]["median"] == "4 h"


def test_atencion_es_la_primera_accion(clean):
    _inc(clean, 3, 10, ack_min=60, started_min=15, close_h=1)     # en progreso antes que asignado
    _inc(clean, 3, 10, close_h=2)                                  # cerrado sin asignar: atendido al cerrar
    m = compute(clean, 30, now=NOW)
    assert m["by_severity"][2]["mtta"]["mean_s"] == (15 + 120) * 60 // 2      # 15 min y 2 h


def test_cumplimiento_por_severidad(clean):
    _inc(clean, 1, 20, ack_min=10, close_h=3)       # a tiempo (15 min / 4 h)
    _inc(clean, 1, 20, ack_min=30, close_h=6)       # tarde en las dos
    m = compute(clean, 30, now=NOW)
    g = m["by_severity"][0]
    assert g["label"].startswith("0-1") and g["ack_sla_pct"] == 50.0 and g["res_sla_pct"] == 50.0
    assert m["ack_sla_pct"] == 50.0 and m["res_sla_pct"] == 50.0


def test_abiertos_vencidos(clean):
    _inc(clean, 1, 2)                        # sev 1 sin atender hace 2 h: pasó 15 min y no 4 h
    _inc(clean, 3, 30, ack_min=5)            # sev 3 atendido, abierto 30 h: pasó 24 h
    _inc(clean, 4, 1, ack_min=5)             # sev 4 dentro de su objetivo
    m = compute(clean, 30, now=NOW)
    assert m["open"] == 3 and m["overdue_count"] == 2
    first = m["overdue"][0]
    assert first["severity"] == 1 and "sin atender" in first["detail"]
    assert "objetivo de solución 24 h" in m["overdue"][1]["detail"]


def test_filtros_de_periodo_y_origen(clean):
    _inc(clean, 2, 24 * 3, ack_min=5, close_h=1, sim=1)
    _inc(clean, 2, 24 * 20, ack_min=5, close_h=1, sim=0)
    assert compute(clean, 7, now=NOW)["incidents"] == 1
    assert compute(clean, 30, now=NOW)["incidents"] == 2
    assert compute(clean, 30, "reales", now=NOW)["incidents"] == 1
    assert compute(clean, 30, "simulados", now=NOW)["incidents"] == 1
    assert compute(clean, 0, now=NOW)["incidents"] == 2


def test_tendencia_y_equipos(clean):
    _inc(clean, 2, 5, ack_min=5, close_h=1)
    _inc(clean, 2, 5, ack_min=5, device="SIM-DIST-SW01")
    m = compute(clean, 7, now=NOW)
    assert len(m["trend"]) == 7 and m["trend"][-1]["created"] == 2 and m["trend"][-1]["closed"] == 1
    assert {d["device"] for d in m["by_device"]} == {"SIM-CORE-RTR01", "SIM-DIST-SW01"}


def test_sin_datos(clean):
    m = compute(clean, 30, now=NOW)
    assert m["incidents"] == 0 and m["mtta"]["mean"] == "—" and m["ack_sla_pct"] is None


@pytest.mark.parametrize("secs, text", [(45, "45 s"), (600, "10 min"), (3600, "1 h"), (5400, "1 h 30 min"),
                                        (86400, "24 h"), (3 * 86400, "3 d"), (3 * 86400 + 7200, "3 d 2 h"),
                                        (None, "—")])
def test_formato_humano(secs, text):
    assert human(secs) == text


def test_objetivos():
    assert target_for(0)[1:] == (900, 4 * 3600) and target_for(2)[1:] == (1800, 8 * 3600)
    assert target_for(7)[0] == "4-7 Otros"


# ---------------------------------------------------------------------------
# 2. Cambios
# ---------------------------------------------------------------------------
def test_metricas_de_cambios(clean):
    ts = "2026-10-25T10:00:00Z"
    for status in ("ejecutado", "ejecutado", "revertido", "fallido", "pendiente"):
        clean.execute("INSERT INTO change_requests (device_name, title, reason, commands, rollback, impact, probability, "
                      "risk_score, risk_level, approvals_required, status, requested_by, created_at, updated_at, "
                      "submitted_at, approved_at) VALUES ('X', 't', 'r', 'c', 'r', 1, 1, 1, 'bajo', 1, ?, 'op', ?, ?, ?, ?)",
                      (status, ts, ts, ts, "2026-10-25T10:30:00Z" if status != "pendiente" else None))
    clean.commit()
    c = compute(clean, 30, now=NOW)["changes"]
    assert c["total"] == 5 and c["finished"] == 4 and c["success_pct"] == 50.0
    assert c["rollbacks"] == 1 and c["failed"] == 1 and c["approval_time"]["mean"] == "30 min"
    assert c["by_risk"]["bajo"] == 5


# ---------------------------------------------------------------------------
# 3. API
# ---------------------------------------------------------------------------
def test_api(client, role_client, clean):
    _inc(clean, 2, 5, ack_min=5, close_h=1)
    r = role_client("auditor").get("/api/metrics?dias=7&origen=simulados")     # el auditor también consulta
    assert r.status_code == 200 and r.json["incidents"] == 1 and r.json["days"] == 7
    assert client.get("/api/metrics?dias=15").status_code == 400
    assert client.get("/api/metrics?origen=otro").status_code == 400
