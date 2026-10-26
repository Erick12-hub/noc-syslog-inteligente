"""
Pruebas de la Fase 10.2: solicitudes de cambio con matriz de riesgo, rollback y ventana.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.changes import risk_level

LOCAL = timezone(timedelta(hours=-5))


def _win(hours_from_now=24, duration=1):
    """Ventana en el formato de <input type="datetime-local"> (hora de Colombia)."""
    start = datetime.now(LOCAL).replace(second=0, microsecond=0) + timedelta(hours=hours_from_now)
    return start.strftime("%Y-%m-%dT%H:%M"), (start + timedelta(hours=duration)).strftime("%Y-%m-%dT%H:%M")


def _dev_id(conn, name="SIM-CORE-RTR01"):
    return conn.execute("SELECT id FROM devices WHERE name = ?", (name,)).fetchone()["id"]


def _body(conn, **kw):
    data = {"device_id": _dev_id(conn), "title": "Documentar enlace de respaldo",
            "reason": "El inventario y el equipo deben describir el enlace al ISP",
            "commands": "interface GigabitEthernet0/0/1\n description Enlace a ISP de respaldo",
            "rollback": "interface GigabitEthernet0/0/1\n no description",
            "verify": "show ip interface brief", "impact": 1, "probability": 1,
            "window_start": "", "window_end": ""}
    data.update(kw)
    return data


def _create(c, conn, **kw):
    return c.post("/api/changes", json=_body(conn, **kw))


def _errors(r):
    return " | ".join(r.json["errors"])


# ---------------------------------------------------------------------------
# 1. Matriz de riesgo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("impact, prob, score, level", [
    (1, 1, 1, "bajo"), (1, 2, 2, "bajo"), (2, 1, 2, "bajo"), (1, 3, 3, "medio"), (3, 1, 3, "medio"),
    (2, 2, 4, "medio"), (2, 3, 6, "alto"), (3, 2, 6, "alto"), (3, 3, 9, "alto"),
])
def test_matriz(impact, prob, score, level):
    assert risk_level(impact, prob) == (score, level)


# ---------------------------------------------------------------------------
# 2. Crear
# ---------------------------------------------------------------------------
def test_cambio_bajo_sin_ventana(client, conn):
    r = _create(client, conn)
    assert r.status_code == 201, r.json
    c = r.json
    assert c["status"] == "borrador" and c["risk_level"] == "bajo" and c["risk_score"] == 1
    assert c["approvals_required"] == 1 and c["window_start"] is None and c["requested_by"] == "tester"
    a = conn.execute("SELECT detail FROM audit_log WHERE action = 'change.create'").fetchone()
    assert "riesgo bajo" in a["detail"]


def test_lineas_vacias_y_comentarios_se_quitan(client, conn):
    r = _create(client, conn, commands="! comentario\ninterface GigabitEthernet0/0/1\n\n description X  \n")
    assert r.json["commands"] == "interface GigabitEthernet0/0/1\n description X"


def test_medio_exige_ventana(client, conn):
    r = _create(client, conn, impact=2, probability=2)
    assert r.status_code == 400 and "obligatoria para riesgo medio" in _errors(r)
    s, e = _win()
    r = _create(client, conn, impact=2, probability=2, window_start=s, window_end=e)
    assert r.status_code == 201 and r.json["risk_level"] == "medio" and r.json["approvals_required"] == 1
    assert r.json["window_start"].endswith("Z")       # se guarda en UTC


def test_alto_exige_dos_aprobaciones(client, conn):
    s, e = _win()
    r = _create(client, conn, impact=3, probability=2, window_start=s, window_end=e)
    assert r.json["risk_level"] == "alto" and r.json["approvals_required"] == 2


def test_hora_de_colombia_a_utc(client, conn):
    s, e = _win()
    r = _create(client, conn, impact=2, probability=2, window_start=s, window_end=e)
    local = datetime.strptime(s, "%Y-%m-%dT%H:%M")
    assert r.json["window_start"] == (local + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:00Z")


# ---------------------------------------------------------------------------
# 3. Impacto mínimo impuesto por los comandos
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("commands, minimum", [
    ("interface GigabitEthernet0/0/1\n no shutdown", "alto"),
    ("interface GigabitEthernet0/0/1\n ip address 10.0.0.1 255.255.255.252", "alto"),
    ("ip route 0.0.0.0 0.0.0.0 10.0.0.2", "alto"),
    ("logging trap warnings", "medio"),
    ("ntp server 192.168.100.1", "medio"),
    ("hostname OTRO-NOMBRE", "medio"),
])
def test_impacto_minimo(client, conn, commands, minimum):
    r = _create(client, conn, commands=commands, rollback="no logging trap" if "logging" in commands
                else "interface GigabitEthernet0/0/1\n shutdown")
    assert r.status_code == 400 and f"mínimo que imponen los comandos ({minimum})" in _errors(r)


def test_interfaz_de_gestion_es_alto(client, conn):
    dev = _dev_id(conn)
    ip = conn.execute("SELECT ip FROM devices WHERE id = ?", (dev,)).fetchone()["ip"]
    conn.execute("INSERT INTO interfaces (device_id, name, status, ip_address, source, created_at, updated_at) "
                 "VALUES (?, 'GigabitEthernet0/0/0', 'up', ?, 'equipo', '2026-10-22T00:00:00Z', "
                 "'2026-10-22T00:00:00Z')", (dev, ip))
    conn.commit()
    r = client.post("/api/changes/assess", json=_body(conn, commands="interface gi0/0/0\n description Gestion"))
    a = r.json["assessment"]
    assert a["min_impact"] == 3 and any("GESTIÓN" in x for x in a["reasons"])


def test_assess_no_guarda(client, conn):
    r = client.post("/api/changes/assess", json=_body(conn, impact=2, probability=3))
    assert r.json["assessment"]["risk_level"] == "alto" and r.json["assessment"]["approvals_required"] == 2
    assert conn.execute("SELECT COUNT(*) FROM change_requests").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# 4. Comandos prohibidos y validaciones
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("line", [
    "configure terminal", "end", "write memory", "copy running-config startup-config", "reload",
    "username admin privilege 15 secret Clave123", "enable secret 5 abc", "snmp-server community x RO",
    "crypto key generate rsa modulus 2048", "no logging host 192.168.100.10", "no archive",
    "do show running-config", "config-register 0x2142",
])
def test_comandos_prohibidos(client, conn, line):
    r = _create(client, conn, commands=line)
    assert r.status_code == 400 and "prohibido" in _errors(r)


def test_prohibidos_tambien_en_rollback(client, conn):
    r = _create(client, conn, rollback="interface GigabitEthernet0/0/1\n no description\nwrite memory")
    assert r.status_code == 400 and "Rollback, línea 3" in _errors(r)


def test_caracteres_de_encadenamiento(client, conn):
    r = _create(client, conn, commands="interface GigabitEthernet0/0/1\n description a; reload")
    assert r.status_code == 400 and "caracteres no permitidos" in _errors(r)


def test_rollback_obligatorio_y_distinto(client, conn):
    assert "Rollback: escriba al menos un comando" in _errors(_create(client, conn, rollback=""))
    same = "interface GigabitEthernet0/0/1\n description Enlace a ISP de respaldo"
    assert "debe deshacerlos" in _errors(_create(client, conn, rollback=same))


def test_verificacion_solo_lectura(client, conn):
    r = _create(client, conn, verify="show clock\nshow running-config")
    assert r.status_code == 400 and "Verificación, línea 2" in _errors(r)


def test_limites_de_lineas(client, conn):
    many = "\n".join(f"interface GigabitEthernet0/0/{i}\n description X" for i in range(16))
    assert "máximo 30 líneas" in _errors(_create(client, conn, commands=many))
    assert "más de 120 caracteres" in _errors(_create(client, conn, commands=" description " + "x" * 120))


@pytest.mark.parametrize("field, value, message", [
    ("title", "abc", "Título"), ("reason", "corto", "Justificación"), ("impact", 7, "Impacto y probabilidad"),
])
def test_campos(client, conn, field, value, message):
    assert message in _errors(_create(client, conn, **{field: value}))


def test_ventanas_invalidas(client, conn):
    s, e = _win()
    assert "indique inicio y fin" in _errors(_create(client, conn, window_start=s))
    assert "posterior al inicio" in _errors(_create(client, conn, window_start=e, window_end=s))
    s5, e5 = _win(duration=5)
    assert "máximo 4 horas" in _errors(_create(client, conn, window_start=s5, window_end=e5))
    sp, ep = _win(hours_from_now=-3)
    assert "ya pasó" in _errors(_create(client, conn, window_start=sp, window_end=ep))
    assert "formato" in _errors(_create(client, conn, window_start="mañana", window_end="tarde"))


def test_equipos_no_validos(client, conn):
    assert "solo en equipos Cisco" in _errors(_create(client, conn, device_id=_dev_id(conn, "SIM-EDGE-FW01")))
    conn.execute("UPDATE devices SET connection_mode = 'ninguno' WHERE name = 'SIM-CORE-RTR01'")
    conn.commit()
    assert "no tiene modo de conexión" in _errors(_create(client, conn))
    assert "Elija el equipo" in _errors(_create(client, conn, device_id="x"))


# ---------------------------------------------------------------------------
# 5. Editar, enviar y cancelar
# ---------------------------------------------------------------------------
def test_editar_borrador(role_client, conn):
    op = role_client("operador", "erick")
    cid = _create(op, conn).json["id"]
    r = op.put(f"/api/changes/{cid}", json=_body(conn, title="Documentar enlaces de respaldo"))
    assert r.status_code == 200 and r.json["title"] == "Documentar enlaces de respaldo"
    otro = role_client("operador", "otro")
    assert otro.put(f"/api/changes/{cid}", json=_body(conn)).status_code == 403
    admin = role_client("admin_seguridad", "jefe")
    assert admin.put(f"/api/changes/{cid}", json=_body(conn)).status_code == 403   # ni el admin edita lo ajeno


def test_enviar_con_linea_base(client, conn):
    assert client.post(f"/api/devices/{_dev_id(conn)}/configs", json={}).status_code == 201
    cid = _create(client, conn).json["id"]
    r = client.post(f"/api/changes/{cid}/submit")
    assert r.status_code == 200 and r.json["status"] == "pendiente" and r.json["submitted_at"]
    assert r.json["baseline_version_id"] is not None and r.json["warnings"] == []
    assert client.get(f"/api/changes/{cid}").json["baseline"]["version_no"] == 1
    assert client.post(f"/api/changes/{cid}/submit").status_code == 409
    assert client.put(f"/api/changes/{cid}", json=_body(conn)).status_code == 409    # ya no se edita
    a = conn.execute("SELECT detail FROM audit_log WHERE action = 'change.submit'").fetchone()
    assert "requiere 1 aprobación" in a["detail"]


def test_enviar_sin_linea_base_avisa(client, conn):
    cid = _create(client, conn).json["id"]
    r = client.post(f"/api/changes/{cid}/submit")
    assert r.status_code == 200 and "línea base" in r.json["warnings"][0]


def test_solo_el_solicitante_envia(client, role_client, conn):
    cid = _create(role_client("operador", "erick"), conn).json["id"]
    assert client.post(f"/api/changes/{cid}/submit").status_code == 403


def test_al_enviar_se_revalida_la_ventana(client, conn):
    s, e = _win()
    cid = _create(client, conn, impact=2, probability=2, window_start=s, window_end=e).json["id"]
    conn.execute("UPDATE change_requests SET window_start = '2026-01-01T10:00:00Z', "
                 "window_end = '2026-01-01T11:00:00Z' WHERE id = ?", (cid,))
    conn.commit()
    r = client.post(f"/api/changes/{cid}/submit")
    assert r.status_code == 400 and "ya pasó" in _errors(r)


def test_ventanas_cruzadas_avisan(client, conn):
    s, e = _win()
    a = _create(client, conn, impact=2, probability=2, window_start=s, window_end=e).json["id"]
    b = _create(client, conn, impact=2, probability=2, window_start=s, window_end=e,
                title="Otro cambio en el mismo router").json["id"]
    client.post(f"/api/changes/{a}/submit")
    r = client.post(f"/api/changes/{b}/submit")
    assert any(f"cambio #{a}" in w for w in r.json["warnings"])


def test_cancelar(client, role_client, conn):
    op = role_client("operador", "erick")
    cid = _create(op, conn).json["id"]
    assert role_client("operador", "otro").post(f"/api/changes/{cid}/cancel", json={"reason": "No va"}).status_code == 403
    assert op.post(f"/api/changes/{cid}/cancel", json={"reason": "no"}).status_code == 400
    r = client.post(f"/api/changes/{cid}/cancel", json={"reason": "Se reprograma"})   # admin
    assert r.status_code == 200 and r.json["status"] == "cancelado" and r.json["closed_at"]
    assert client.post(f"/api/changes/{cid}/cancel", json={"reason": "Otra vez"}).status_code == 409


def test_listas_por_estado(client, conn):
    a = _create(client, conn).json["id"]
    b = _create(client, conn, title="Cambio que se cancela").json["id"]
    client.post(f"/api/changes/{b}/cancel", json={"reason": "Ya no se necesita"})
    assert [c["id"] for c in client.get("/api/changes").json] == [a]
    assert [c["id"] for c in client.get("/api/changes?estado=cerrados").json] == [b]
    assert len(client.get("/api/changes?estado=todos").json) == 2
    assert client.get("/api/changes?estado=raro").status_code == 400
    assert client.get("/api/changes/999").status_code == 404


# ---------------------------------------------------------------------------
# 6. Roles
# ---------------------------------------------------------------------------
def test_auditor_solo_consulta(client, role_client, conn):
    _create(client, conn)
    aud = role_client("auditor")
    assert len(aud.get("/api/changes").json) == 1
    assert aud.post("/api/changes", json=_body(conn)).status_code == 403
    page = aud.get("/cambios")
    assert page.status_code == 200 and "btn-new" not in page.get_data(as_text=True)   # sin botón de crear
