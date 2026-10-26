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


@pytest.fixture(autouse=True)
def reset_storm():
    """El limitador de tormentas guarda estado en memoria: se limpia en cada prueba."""
    from app.security import STORM
    STORM.reset()
    yield
    STORM.reset()


@pytest.fixture(autouse=True)
def no_real_telegram(monkeypatch):
    """Fase 11: aunque el .env tenga el token del bot, las pruebas nunca envían avisos reales
    (ni dentro de la web ni en funciones que leen Config directamente, como la consistencia)."""
    monkeypatch.setattr(Config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(Config, "TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr(Config, "NOTIFY_SIMULATE", False)
    monkeypatch.setattr(Config, "AI_ASSISTANT_ENABLED", True)


@pytest.fixture(autouse=True)
def fast_password_hash(monkeypatch):
    """
    En la aplicación real las contraseñas usan scrypt (lento a propósito, ~0,2 s).
    En las pruebas se usa un hash rápido para no multiplicar el tiempo por 6;
    test_auth.py verifica aparte que la aplicación real usa scrypt.
    """
    import app.auth
    monkeypatch.setattr(app.auth, "HASH_METHOD", "pbkdf2:sha256:1000")


@pytest.fixture
def app(tmp_path):
    class TestConfig(Config):
        TESTING = True
        DATABASE_PATH = tmp_path / "test.db"
        DEFAULT_OPERATOR = "tester"
        # Fase 11: las pruebas NUNCA usan el bot real aunque el .env tenga el token
        TELEGRAM_BOT_TOKEN = ""
        TELEGRAM_CHAT_ID = ""
        NOTIFY_SIMULATE = False
        AI_ASSISTANT_ENABLED = True

    application = create_app(TestConfig)   # crea las tablas
    conn = connect(TestConfig.DATABASE_PATH)
    seed_devices(conn)                     # carga los equipos simulados
    conn.close()
    return application


TEST_PASSWORD = "ClavePrueba2026"     # solo para la base TEMPORAL de las pruebas


def make_user(app, username, role):
    """Crea un usuario en la base temporal de la prueba."""
    from app.auth import create_user
    conn = connect(app.config["DATABASE_PATH"])
    try:
        create_user(conn, username, TEST_PASSWORD, role, f"Usuario de prueba {role}")
    finally:
        conn.close()


def login(client, username, password=TEST_PASSWORD):
    """
    Inicia sesión como lo hace un navegador: abre /login (recibe el token CSRF),
    envía el formulario y luego deja el token nuevo como encabezado por defecto,
    igual que hace common.js en las páginas.
    """
    client.get("/login")
    with client.session_transaction() as s:
        token = s.get("csrf", "")
    r = client.post("/login", data={"username": username, "password": password, "csrf_token": token})
    with client.session_transaction() as s:
        client.environ_base["HTTP_X_CSRF_TOKEN"] = s.get("csrf", "")
    return r


@pytest.fixture
def anon_client(app):
    """Cliente SIN sesión (para probar que todo exige iniciar sesión)."""
    return app.test_client()


@pytest.fixture
def client(app):
    """
    Cliente con sesión de administrador de seguridad, usuario 'tester'.
    Las pruebas del Corte 2 esperan que el responsable sea 'tester': ahora
    sale del usuario de la sesión, no de DEFAULT_OPERATOR.
    """
    make_user(app, "tester", "admin_seguridad")
    c = app.test_client()
    login(c, "tester")
    return c


@pytest.fixture
def role_client(app):
    """Fábrica: role_client("operador") devuelve un cliente con sesión de ese rol."""
    def _make(role, username=None):
        username = username or role.replace("_", "")
        make_user(app, username, role)
        c = app.test_client()
        login(c, username)
        return c
    return _make


@pytest.fixture
def conn(app):
    c = connect(app.config["DATABASE_PATH"])
    yield c
    c.close()
