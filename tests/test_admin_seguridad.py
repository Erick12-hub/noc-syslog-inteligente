"""
Pruebas de la Fase 8 (paso 8.3): ventana de administración de seguridad.
El cliente 'client' es el administrador 'tester'. Usuarios SIMULADOS.
"""
import pytest

from tests.conftest import TEST_PASSWORD, login, make_user


def _uid(conn, username):
    return conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]


# ---------------------------------------------------------------------------
# 1. Solo el administrador de seguridad entra
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ["operador", "auditor"])
def test_otros_roles_no_entran(role_client, role):
    c = role_client(role)
    assert c.get("/api/admin/users").status_code == 403
    assert c.get("/api/admin/security").status_code == 403
    assert c.post("/api/admin/users", json={}).status_code == 403
    assert c.get("/seguridad").status_code == 403
    assert 'href="/seguridad"' not in c.get("/").get_data(as_text=True)


def test_admin_ve_la_ventana(client):
    assert client.get("/seguridad").status_code == 200
    assert 'href="/seguridad"' in client.get("/").get_data(as_text=True)


# ---------------------------------------------------------------------------
# 2. Gestión de usuarios
# ---------------------------------------------------------------------------
def test_crear_usuario_desde_la_web(client, conn):
    r = client.post("/api/admin/users", json={"username": "operador2", "role": "operador",
                                              "full_name": "Turno mañana", "password": TEST_PASSWORD})
    assert r.status_code == 201 and r.json["role"] == "operador"
    assert "password_hash" not in r.json                               # el hash nunca sale
    row = conn.execute("SELECT actor FROM audit_log WHERE action = 'user.create' "
                       "AND detail LIKE '%operador2%'").fetchone()
    assert row["actor"] == "tester"


def test_crear_usuario_invalido(client):
    r = client.post("/api/admin/users", json={"username": "X", "role": "jefe", "password": "corta"})
    assert r.status_code == 400 and len(r.json["errors"]) >= 3


def test_listado_sin_hashes(client):
    users = client.get("/api/admin/users").json
    assert users and all("password_hash" not in u for u in users)


def test_cambiar_rol_y_aplica_de_inmediato(app, client, conn):
    make_user(app, "erick", "operador")
    other = app.test_client()
    login(other, "erick")
    assert other.get("/api/audit").status_code == 403                 # operador: sin auditoría
    r = client.post(f"/api/admin/users/{_uid(conn, 'erick')}/role", json={"role": "auditor"})
    assert r.status_code == 200 and r.json["role"] == "auditor"
    assert other.get("/api/audit").status_code == 200                  # el cambio aplica sin volver a entrar
    assert "operador->auditor" in conn.execute(
        "SELECT detail FROM audit_log WHERE action = 'user.role'").fetchone()["detail"]


def test_no_puede_cambiar_su_propio_rol(client, conn):
    r = client.post(f"/api/admin/users/{_uid(conn, 'tester')}/role", json={"role": "operador"})
    assert r.status_code == 409


def test_desactivar_corta_la_sesion(app, client, conn):
    make_user(app, "erick", "operador")
    other = app.test_client()
    login(other, "erick")
    assert other.get("/api/events").status_code == 200
    r = client.post(f"/api/admin/users/{_uid(conn, 'erick')}/active", json={"active": False})
    assert r.status_code == 200 and r.json["active"] == 0
    assert other.get("/api/events").status_code == 401                # sesión cortada
    assert login(app.test_client(), "erick").status_code == 401         # y no puede volver a entrar


def test_no_puede_desactivarse_a_si_mismo(client, conn):
    r = client.post(f"/api/admin/users/{_uid(conn, 'tester')}/active", json={"active": False})
    assert r.status_code == 409


def test_desbloquear(app, client, conn):
    make_user(app, "erick", "operador")
    for _ in range(5):
        login(app.test_client(), "erick", "Equivocada2026")
    assert login(app.test_client(), "erick").status_code == 423       # bloqueada
    r = client.post(f"/api/admin/users/{_uid(conn, 'erick')}/unlock")
    assert r.status_code == 200 and r.json["locked"] is False
    assert login(app.test_client(), "erick").status_code == 302


def test_restablecer_contrasena(app, client, conn):
    make_user(app, "erick", "operador")
    uid = _uid(conn, "erick")
    assert client.post(f"/api/admin/users/{uid}/password", json={"password": "corta"}).status_code == 400
    nueva = "NuevaClave2026x"
    assert client.post(f"/api/admin/users/{uid}/password", json={"password": nueva}).status_code == 200
    assert login(app.test_client(), "erick").status_code == 401          # la anterior ya no sirve
    assert login(app.test_client(), "erick", nueva).status_code == 302
    detail = conn.execute("SELECT detail FROM audit_log WHERE action = 'user.password_reset'").fetchone()["detail"]
    assert nueva not in detail                                           # la clave nunca va a la auditoría


def test_renombrar(client, conn):
    r = client.post(f"/api/admin/users/{_uid(conn, 'tester')}/name", json={"full_name": "Erick Castro"})
    assert r.status_code == 200 and r.json["full_name"] == "Erick Castro"
    assert client.post(f"/api/admin/users/{_uid(conn, 'tester')}/name", json={"full_name": "x"}).status_code == 400


def test_usuario_inexistente(client):
    assert client.post("/api/admin/users/999/unlock").status_code == 404


# ---------------------------------------------------------------------------
# 3. Resumen de seguridad
# ---------------------------------------------------------------------------
def test_resumen_de_seguridad(app, client, role_client):
    make_user(app, "erick", "operador")
    login(app.test_client(), "erick", "Equivocada2026")                  # 1 intento fallido
    role_client("auditor").post("/api/devices", json={})                 # 1 acción bloqueada por rol
    s = client.get("/api/admin/security").json
    assert s["failed_logins_24h"] == 1 and s["blocked_actions_24h"] >= 1
    assert s["chain"]["ok"] is True and s["users_total"] == 3
    names = [p[0] for p in s["parameters"]]
    assert "Intentos fallidos antes de bloquear" in names and "Hash de contraseñas" in names
    assert any(e["action"] == "auth.login_fallido" for e in s["recent"])
