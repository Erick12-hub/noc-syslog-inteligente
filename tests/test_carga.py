"""
Pruebas de la Fase 12: prueba de carga reducida (scripts/prueba_carga.py).

Valores pequeños para que la batería siga siendo rápida; el script completo
se ejecuta aparte y deja su reporte en docs/pruebas/prueba_carga.md.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import prueba_carga as pc  # noqa: E402
from app.config import Config  # noqa: E402


@pytest.fixture
def loaded_db(tmp_path):
    db = tmp_path / "carga.db"
    pc.prepare_db(db).close()
    return db


def test_messages_are_simulated_documentation_ips():
    for i in range(20):
        ip, raw = pc.message(i)
        assert ip.startswith(("192.0.2.", "198.51.100."))
        assert "SIM" in raw or "sim_user" in raw


def test_percentile():
    assert pc.percentile([1, 2, 3, 4, 5], 50) == 3
    assert pc.percentile([], 95) == 0.0
    assert pc.percentile([10], 99) == 10


def test_ingest_load_without_errors(loaded_db):
    r = pc.test_ingest(loaded_db, 200)
    assert r["errores"] == 0 and r["mensajes"] == 200
    assert r["por_segundo"] > 0 and r["p95"] >= r["p50"]


def test_concurrent_writers_keep_audit_chain(loaded_db):
    r = pc.test_concurrency(loaded_db, threads=3, per_thread=40)
    assert r["errores"] == 0
    assert r["cadena_ok"] is True


def test_storm_control_accepts_exactly_the_limit(loaded_db, monkeypatch):
    monkeypatch.setattr(Config, "STORM_MAX_PER_MINUTE", 30)
    r = pc.test_storm(loaded_db, extra=12)
    assert r["aceptados"] == 30 and r["descartados"] == 12 and r["ok"]


def test_web_queries_respond_with_load(loaded_db):
    pc.test_ingest(loaded_db, 100)
    r = pc.test_web(loaded_db, repeat=2)
    assert all(v["codigos"] == [200] for v in r.values())


def test_markdown_report_renders(loaded_db):
    ing = pc.test_ingest(loaded_db, 50)
    con = pc.test_concurrency(loaded_db, 2, 10)
    st = pc.test_storm(loaded_db, extra=5)
    web = pc.test_web(loaded_db, 1)
    md = pc.render_markdown({"fecha": "2026-10-26 10:00", "equipo": "prueba", "ingesta": ing,
                             "concurrencia": con, "tormenta": st, "web": web, "conclusion": "ok"})
    assert "# Prueba de carga" in md and "SIMULADOS" in md and "Control de tormentas" in md
