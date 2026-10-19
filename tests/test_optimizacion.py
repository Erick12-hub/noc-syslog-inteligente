"""
Pruebas de la Fase 7 (pasos 7.4 y 7.5): optimización de la base de datos,
paginación y servidor sin modo depuración. Datos SIMULADOS.
"""
from pathlib import Path

from app.config import Config
from app.db import INDEXES, connect, init_db
from app.ingest import ingest

ROOT = Path(__file__).resolve().parent.parent


def _plan(conn, sql, params):
    """EXPLAIN QUERY PLAN: cómo piensa SQLite ejecutar la consulta (qué índice usa)."""
    return " ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, params))


def _load(conn, n):
    """Carga n eventos DISTINTOS. Ojo: la huella de deduplicación ignora los números,
    así que "mensaje 1" y "mensaje 2" serían el mismo evento; se usan letras (aa, ab, ...)."""
    for i in range(n):
        word = chr(97 + i // 26) + chr(97 + i % 26)
        ingest(conn, f"<190>{i}: *Oct  5 10:00:00.000: SIM-CORE-RTR01 %SYS-6-TEST: mensaje simulado {word}",
               "192.0.2.1", "simulador")


# ---------------------------------------------------------------------------
# 7.4 Base de datos
# ---------------------------------------------------------------------------
def test_modo_wal_activo(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_indices_creados_y_obsoleto_eliminado(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {name for name, _ in INDEXES} <= names
    assert "idx_events_fp" not in names


def test_deduplicacion_usa_el_indice_compuesto(conn):
    plan = _plan(conn, "SELECT id FROM syslog_events WHERE fingerprint = ? AND received_at >= ?",
                 ("x", "2026-01-01T00:00:00Z"))
    assert "idx_events_fp_time" in plan


def test_filtro_por_equipo_usa_indice(conn):
    plan = _plan(conn, "SELECT id FROM syslog_events WHERE device_id = ? AND received_at >= ?",
                 (1, "2026-01-01T00:00:00Z"))
    assert "idx_events_device_time" in plan


def test_init_db_es_idempotente(tmp_path):
    db = tmp_path / "doble.db"
    for _ in range(2):            # arrancar dos veces no debe fallar ni duplicar nada
        c = connect(db)
        init_db(c)
        c.close()


# ---------------------------------------------------------------------------
# 7.4 Paginación
# ---------------------------------------------------------------------------
def test_paginacion_de_eventos(client, conn):
    _load(conn, 25)
    r = client.get("/api/events?limit=10&page=3")
    assert r.status_code == 200 and len(r.json) == 5           # 25 = 10 + 10 + 5
    assert r.headers["X-Total-Count"] == "25" and r.headers["X-Total-Pages"] == "3"
    primera = client.get("/api/events?limit=10&page=1").json
    assert primera[0]["id"] > primera[-1]["id"]                 # lo más reciente primero


def test_paginas_no_se_repiten(client, conn):
    _load(conn, 12)
    p1 = {e["id"] for e in client.get("/api/events?limit=5&page=1").json}
    p2 = {e["id"] for e in client.get("/api/events?limit=5&page=2").json}
    assert len(p1) == 5 and len(p2) == 5 and not (p1 & p2)


def test_pagina_fuera_de_rango(client, conn):
    _load(conn, 3)
    r = client.get("/api/events?limit=10&page=9")
    assert r.status_code == 200 and r.json == [] and r.headers["X-Total-Count"] == "3"
    assert client.get("/api/events?page=0").status_code == 400


def test_total_respeta_los_filtros(client, conn):
    _load(conn, 4)
    ingest(conn, "<187>9: *Oct  5 10:15:42.551: SIM-CORE-RTR01 %LINK-3-UPDOWN: Interface Gi0/1, "
                 "changed state to down", "192.0.2.1", "simulador")
    r = client.get("/api/events?severity=3")
    assert r.headers["X-Total-Count"] == "1"


# ---------------------------------------------------------------------------
# 7.5 Servidor
# ---------------------------------------------------------------------------
def test_depuracion_apagada_por_defecto():
    assert Config.FLASK_DEBUG is False


def test_run_py_no_fija_debug_true():
    assert "debug=True" not in (ROOT / "run.py").read_text(encoding="utf-8")


def test_serve_py_usa_waitress_sin_depuracion():
    text = (ROOT / "serve.py").read_text(encoding="utf-8")
    assert "from waitress import serve" in text and "app.debug = False" in text
    import waitress  # noqa: F401  (la dependencia está instalada)
