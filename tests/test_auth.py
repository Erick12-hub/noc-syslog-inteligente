"""
Pruebas de la Fase 8 (paso 8.1): inicio de sesión, bloqueo, CSRF, roles y
separación de funciones. Usuarios y datos SIMULADOS (base temporal).
"""
from pathlib import Path

import pytest

from app.auth import allowed_roles, create_user, validate_password
from app.db import now_iso
from tests.conftest import TEST_PASSWORD, login, make_user

ROOT = Path(__file__).resolve().parent.parent
NEW_DEVICE = {"name": "SIM-TEST-SW77", "ip": "192.0.2.77", "vendor": "Cisco", "status": "activo"}


def _csrf(c):
    with c.session_transaction() as s:
        return s.get("csrf", "")


# ---------------------------------------------------------------------------
# 1. Sin sesión no se entra a nada (salvo /login, /static y /api/health)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/api/events", "/api/devices", "/api/incidents", "/api/audit",
                                  "/api/dashboard", "/api/auth/me"])
def test_api_sin_sesion_responde_401(anon_client, path):
    r = anon_client.get(path)
    assert r.status_code == 401 and r.json["errors"] == ["Debe iniciar sesión"]


def test_pagina_sin_sesion_redirige_al_login(anon_client):
    r = anon_client.get("/eventos")
    assert r.status_code == 302 and r.headers["Location"].startswith("/login?next=/eventos")


def test_rutas_publicas(anon_client):
    assert anon_client.get("/login").status_code == 200
    assert anon_client.get("/api/health").status_code == 200
    r = anon_client.get("/static/styles.css")
    assert r.status_code == 200
    r.close()


# ---------------------------------------------------------------------------
# 2. Inicio de sesión
# ---------------------------------------------------------------------------
def test_login_correcto_y_auditado(app, anon_client, conn):
    make_user(app, "erick", "operador")
    r = login(anon_client, "erick")
    assert r.status_code == 302 and r.headers["Location"] == "/"
    assert anon_client.get("/api/auth/me").json["role"] == "operador"
    row = conn.execute("SELECT actor, result FROM audit_log WHERE action = 'auth.login'").fetchone()
    assert row["actor"] == "erick" and row["result"] == "ok"


def test_mismo_mensaje_si_el_usuario_no_existe(app, anon_client, conn):
    make_user(app, "erick", "operador")
    bad_pass = login(anon_client, "erick", "OtraClave2026")
    no_user = login(anon_client, "fantasma", "OtraClave2026")
    assert bad_pass.status_code == no_user.status_code == 401
    msg = "Usuario o contraseña incorrectos."
    assert msg in bad_pass.get_data(as_text=True) and msg in no_user.get_data(as_text=True)
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'auth.login_fallido'").fetchone()[0] == 2


def test_bloqueo_tras_5_intentos_fallidos(app, anon_client, conn):
    make_user(app, "erick", "operador")
    for _ in range(4):
        assert login(anon_client, "erick", "Equivocada2026").status_code == 401
    r = login(anon_client, "erick", "Equivocada2026")            # quinto intento
    assert r.status_code == 423 and "bloqueada" in r.get_data(as_text=True)
    # Bloqueada: ni siquiera la contraseña CORRECTA entra
    assert login(anon_client, "erick").status_code == 423
    assert conn.execute("SELECT result FROM audit_log WHERE action = 'auth.bloqueo'").fetchone()["result"] == "alerta"


def test_la_cuenta_bloqueada_conserva_los_fallidos(app, anon_client, conn):
    # Hallazgo de la prueba en vivo (8.3): se veía "bloqueado" con 0 fallidos
    make_user(app, "erick", "operador")
    for _ in range(5):
        login(anon_client, "erick", "Equivocada2026")
    row = conn.execute("SELECT failed_attempts, locked_until FROM users WHERE username = 'erick'").fetchone()
    assert row["failed_attempts"] == 5 and row["locked_until"]


def test_tras_vencer_el_bloqueo_se_cuenta_desde_cero(app, anon_client, conn):
    make_user(app, "erick", "operador")
    conn.execute("UPDATE users SET failed_attempts = 5, locked_until = '2000-01-01T00:00:00Z' "
                 "WHERE username = 'erick'")
    conn.commit()
    assert login(anon_client, "erick", "Equivocada2026").status_code == 401    # NO se re-bloquea
    row = conn.execute("SELECT failed_attempts, locked_until FROM users WHERE username = 'erick'").fetchone()
    assert row["failed_attempts"] == 1 and row["locked_until"] is None


def test_el_bloqueo_vence(app, anon_client, conn):
    make_user(app, "erick", "operador")
    conn.execute("UPDATE users SET locked_until = '2000-01-01T00:00:00Z' WHERE username = 'erick'")
    conn.commit()
    assert login(anon_client, "erick").status_code == 302


def test_usuario_desactivado_no_entra_y_pierde_la_sesion(app, role_client, anon_client, conn):
    c = role_client("operador", "erick")
    conn.execute("UPDATE users SET active = 0 WHERE username = 'erick'")
    conn.commit()
    assert c.get("/api/events").status_code == 401                 # la sesión abierta deja de servir
    assert login(anon_client, "erick").status_code == 401


def test_no_redirige_a_otros_sitios(app, anon_client):
    make_user(app, "erick", "operador")
    anon_client.get("/login")
    r = anon_client.post("/login", data={"username": "erick", "password": TEST_PASSWORD,
                                         "csrf_token": _csrf(anon_client), "next": "//sitio-malicioso.com"})
    assert r.headers["Location"] == "/"


def test_cookie_de_sesion_segura(app, anon_client):
    make_user(app, "erick", "operador")
    r = login(anon_client, "erick")
    cookie = r.headers["Set-Cookie"]
    assert "noc_sesion=" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie


@pytest.mark.parametrize("role", ["operador", "auditor", "admin_seguridad"])
def test_todos_los_roles_pueden_cerrar_sesion(role_client, role, conn):
    # Hallazgo de la prueba en vivo: el auditor recibía 403 al pulsar "Salir"
    c = role_client(role)
    r = c.post("/logout")
    assert r.status_code == 302 and r.headers["Location"] == "/login"
    assert c.get("/api/events").status_code == 401                 # la sesión ya no sirve
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'auth.logout'").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# 3. CSRF
# ---------------------------------------------------------------------------
def test_peticion_sin_token_csrf_se_bloquea_y_audita(client, conn):
    del client.environ_base["HTTP_X_CSRF_TOKEN"]
    r = client.post("/api/devices", json=NEW_DEVICE)
    assert r.status_code == 403 and "CSRF" in r.json["errors"][0]
    assert conn.execute("SELECT result FROM audit_log WHERE action = 'security.csrf'").fetchone()["result"] == "bloqueado"
    assert conn.execute("SELECT COUNT(*) FROM devices WHERE name = 'SIM-TEST-SW77'").fetchone()[0] == 0


def test_login_sin_token_csrf(app, anon_client):
    make_user(app, "erick", "operador")
    r = anon_client.post("/login", data={"username": "erick", "password": TEST_PASSWORD})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 4. Roles
# ---------------------------------------------------------------------------
def test_operador(role_client, conn):
    c = role_client("operador", "erick")
    assert c.post("/api/devices", json=NEW_DEVICE).status_code == 201
    # El responsable en la auditoría es el usuario de la sesión
    assert conn.execute("SELECT actor FROM audit_log WHERE action = 'device.create'").fetchone()["actor"] == "erick"
    assert c.get("/api/audit").status_code == 403                   # no ve la auditoría
    assert c.get("/auditoria").status_code == 403
    assert c.post("/api/proposals/1/review", json={}).status_code == 403   # no aprueba


def test_auditor_solo_lectura(role_client):
    c = role_client("auditor")
    assert c.get("/api/events").status_code == 200
    assert c.get("/api/audit").status_code == 200
    assert c.post("/api/devices", json=NEW_DEVICE).status_code == 403
    assert c.post("/api/incidents", json={"title": "x" * 5, "severity": 3}).status_code == 403
    assert c.get("/api/console/allowed?vendor=Cisco").status_code == 403
    assert "modo de solo lectura" in c.get("/").get_data(as_text=True)


def test_menu_segun_el_rol(role_client):
    html = role_client("operador").get("/").get_data(as_text=True)
    assert 'href="/consola"' in html and 'href="/auditoria"' not in html
    html = role_client("auditor").get("/").get_data(as_text=True)
    assert 'href="/auditoria"' in html and 'href="/consola"' not in html


def test_rechazos_por_rol_quedan_auditados(role_client, conn):
    role_client("auditor").post("/api/devices", json=NEW_DEVICE)
    row = conn.execute("SELECT actor, detail, result FROM audit_log WHERE action = 'security.forbidden'").fetchone()
    assert row["actor"] == "auditor" and "rol=auditor" in row["detail"] and row["result"] == "bloqueado"


@pytest.mark.parametrize("endpoint, method, roles", [
    ("events.list_events", "GET", {"operador", "auditor", "admin_seguridad"}),
    ("devices.create_device", "POST", {"operador", "admin_seguridad"}),
    ("proposals.review", "POST", {"admin_seguridad"}),
    ("audit.list_audit", "GET", {"auditor", "admin_seguridad"}),
    ("auth.logout", "POST", {"operador", "auditor", "admin_seguridad"}),
    ("ruta.nueva_que_cambia_datos", "POST", {"operador", "admin_seguridad"}),   # regla por defecto
])
def test_tabla_de_permisos(endpoint, method, roles):
    assert set(allowed_roles(endpoint, method)) == roles


# ---------------------------------------------------------------------------
# 5. Separación de funciones
# ---------------------------------------------------------------------------
def test_nadie_aprueba_su_propia_propuesta(client, conn):
    conn.execute("INSERT INTO action_proposals (proposed_by, command, risk, status, created_at) "
                 "VALUES ('tester', 'show clock', 'bajo', 'pendiente', ?)", (now_iso(),))
    conn.commit()
    pid = conn.execute("SELECT MAX(id) FROM action_proposals").fetchone()[0]
    r = client.post(f"/api/proposals/{pid}/review", json={"decision": "aprobar", "comment": "Me la apruebo"})
    assert r.status_code == 403 and "su propia propuesta" in r.json["errors"][0]


# ---------------------------------------------------------------------------
# 6. Contraseñas y usuarios
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("password, problem", [
    ("Corta123", "al menos 10 caracteres"),
    ("SoloLetrasLargas", "combinar letras y números"),
    ("erick2026abc", "no puede contener el nombre de usuario"),
])
def test_politica_de_contrasenas(password, problem):
    assert any(problem in e for e in validate_password(password, "erick"))


def test_contrasena_guardada_como_hash(app, conn):
    make_user(app, "erick", "operador")
    stored = conn.execute("SELECT password_hash FROM users WHERE username = 'erick'").fetchone()[0]
    assert TEST_PASSWORD not in stored and stored.startswith("pbkdf2:")   # hash, no el texto


def test_la_aplicacion_real_usa_scrypt():
    assert 'HASH_METHOD = "scrypt"' in (ROOT / "app/auth.py").read_text(encoding="utf-8")


def test_usuario_duplicado_o_invalido(app, conn):
    make_user(app, "erick", "operador")
    with pytest.raises(ValueError) as e:
        create_user(conn, "erick", TEST_PASSWORD, "operador")
    assert "ya existe" in e.value.args[0][0]
    with pytest.raises(ValueError) as e:
        create_user(conn, "1malo con espacios", TEST_PASSWORD, "superusuario")
    assert len(e.value.args[0]) == 2                                   # usuario y rol inválidos


def test_no_hay_usuarios_por_defecto(conn):
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Corrección 2026-10-25: el ícono de la pestaña no debe romper el inicio de sesión
# ---------------------------------------------------------------------------
def test_favicon_publico(app):
    r = app.test_client().get("/favicon.ico")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml"


@pytest.mark.parametrize("extra", ["/favicon.ico", "/no-existe", "/api/devices"])
def test_peticion_sin_sesion_no_borra_el_token_del_login(app, extra):
    """El navegador pide /favicon.ico (u otra ruta) entre mostrar el login y enviarlo:
    el token del formulario debe seguir siendo válido."""
    make_user(app, "erick", "operador")
    c = app.test_client()
    c.get("/login")
    with c.session_transaction() as s:
        token = s["csrf"]
    c.get(extra)
    r = c.post("/login", data={"username": "erick", "password": TEST_PASSWORD, "csrf_token": token})
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
