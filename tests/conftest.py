"""
Configuración compartida de las pruebas (pytest).

Cada prueba usa una base de datos TEMPORAL nueva (tmp_path), así las pruebas
nunca tocan data/noc.db y no dependen unas de otras.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app          # noqa: E402
from app.config import Config       # noqa: E402
from app.db import connect          # noqa: E402
from app.seed import seed_devices   # noqa: E402


@pytest.fixture
def app(tmp_path):
    class TestConfig(Config):
        TESTING = True
        DATABASE_PATH = tmp_path / "test.db"
        DEFAULT_OPERATOR = "tester"

    application = create_app(TestConfig)   # crea las tablas
    conn = connect(TestConfig.DATABASE_PATH)
    seed_devices(conn)                     # carga los equipos simulados
    conn.close()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def conn(app):
    c = connect(app.config["DATABASE_PATH"])
    yield c
    c.close()
