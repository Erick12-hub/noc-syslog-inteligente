"""
Pruebas de la Fase 9.1: gestor de conexiones con trazabilidad.

No se conecta a ningún equipo: se usan las salidas de ejemplo de samples/cli/
(formato real de un Catalyst 8200L-1N-4T y un Catalyst 2960-24TT-L, con números
de serie SIMULADOS) y transportes falsos para simular fallas y llaves SSH.
"""
import hashlib
from pathlib import Path

import pytest

import app.connector as connector
from app.config import Config
from app.connector import NetmikoTransport, parse_identity, run_session
from app.db import init_db

SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "cli"
XE_VERSION = (SAMPLES / "cisco_xe" / "show_version.txt").read_text(encoding="utf-8")
IOS_VERSION = (SAMPLES / "cisco_ios" / "show_version.txt").read_text(encoding="utf-8")


def _dev(conn, name):
    return conn.execute("SELECT * FROM devices WHERE name = ?", (name,)).fetchone()


def _id(conn, name):
    return _dev(conn, name)["id"]


class FakeTransport:
    """Transporte de prueba: responde con textos fijos y puede fallar o cambiar la llave."""

    def __init__(self, outputs=None, transport="ssh", host_key_fp=None, fail_open=False):
        self.outputs = outputs or {"show version": IOS_VERSION}
        self.transport, self.target = transport, "192.0.2.10:22"
        self.host_key_fp, self.fail_open = host_key_fp, fail_open
        self.sent = []

    def open(self):
        if self.fail_open:
            raise connector.ConnectionError_("No se pudo conectar (ssh 192.0.2.10:22): NetmikoTimeoutException")

    def send(self, command):
        self.sent.append(command)
        return self.outputs.get(command, "salida de prueba")

    def close(self):
        pass


@pytest.fixture
def fake(monkeypatch):
    """Instala un transporte falso; devuelve una función para configurarlo."""
    holder = {}

    def _install(**kwargs):
        holder["t"] = FakeTransport(**kwargs)
        monkeypatch.setattr(connector, "make_transport", lambda device, conn: holder["t"])
        return holder["t"]
    return _install


def _ssh_switch(conn):
    conn.execute("UPDATE devices SET connection_mode = 'ssh', platform = 'cisco_ios' WHERE name = 'SIM-DIST-SW01'")
    conn.commit()
    return _dev(conn, "SIM-DIST-SW01")


@pytest.fixture
def ssh_creds(monkeypatch):
    monkeypatch.setattr(Config, "SSH_USERNAME", "noc_lectura")
    monkeypatch.setattr(Config, "SSH_PASSWORD", "ClaveDePrueba2026")


# ---------------------------------------------------------------------------
# 1. Identidad del equipo físico
# ---------------------------------------------------------------------------
def test_identidad_router_c8200():
    r = parse_identity("cisco_xe", XE_VERSION)
    assert (r["serial"], r["model"], r["version"]) == ("FGL2601SIM1", "C8200L-1N-4T", "17.09.04a")
    assert r["warnings"] == []


def test_identidad_switch_2960():
    r = parse_identity("cisco_ios", IOS_VERSION)
    assert (r["serial"], r["model"], r["version"]) == ("FOC1234SIM3", "WS-C2960-24TT-L", "15.2(7)E8")
    assert r["warnings"] == []                       # imagen k9: soporta SSH


def test_switch_sin_k9_avisa_que_no_hay_ssh():
    text = IOS_VERSION.replace("LANBASEK9", "LANBASE").replace("lanbasek9", "lanbase")
    assert any("k9" in w for w in parse_identity("cisco_ios", text)["warnings"])


def test_router_en_modo_sdwan_avisa():
    text = XE_VERSION.replace("Router operating mode: Autonomous", "Router operating mode: Controller-Managed")
    assert any("SD-WAN" in w for w in parse_identity("cisco_xe", text)["warnings"])


def test_identidad_fortinet_y_huawei():
    f = parse_identity("fortinet", "Version: FortiGate-60F v7.4.3,build2573,240201 (GA.F)\n"
                                   "Serial-Number: FGT60FSIM0000001\nHostname: SIM-EDGE-FW01")
    assert (f["serial"], f["model"], f["version"]) == ("FGT60FSIM0000001", "FortiGate-60F", "v7.4.3")
    h = parse_identity("huawei", "Huawei Versatile Routing Platform Software\n"
                                 "VRP (R) software, Version 5.170 (AR6120 V300R022C00SPC100)\n"
                                 "HUAWEI AR6120 uptime is 12 days, 4 hours")
    assert h["model"] == "AR6120" and h["serial"] is None
    assert any("número de serie" in w for w in h["warnings"])   # se pide display esn


# ---------------------------------------------------------------------------
# 2. Sesión completa (modo simulado, sin red)
# ---------------------------------------------------------------------------
def test_sesion_simulada_identifica_y_registra(role_client, conn):
    c = role_client("operador", "erick")
    dev = _id(conn, "SIM-CORE-RTR01")
    r = c.post(f"/api/devices/{dev}/session", json={"commands": ["show ip interface brief"]})
    assert r.status_code == 200
    s = r.json
    assert s["status"] == "cerrada" and s["transport"] == "simulado" and s["started_by"] == "erick"
    assert s["serial_number"] == "FGL2601SIM1" and s["model"] == "C8200L-1N-4T" and s["is_simulated"] == 1
    assert [x["command"] for x in s["commands"]] == ["show version", "show ip interface brief"]
    out = s["commands"][1]
    assert "GigabitEthernet0/0/0" in out["output"]
    assert out["output_sha256"] == hashlib.sha256(out["output"].encode()).hexdigest()
    # El inventario guarda lo que se leyó del equipo físico
    d = _dev(conn, "SIM-CORE-RTR01")
    assert d["serial_number"] == "FGL2601SIM1" and d["detected_version"] == "17.09.04a" and d["last_identified_at"]
    # Y todo queda en la auditoría con el usuario real
    actions = [r["action"] for r in conn.execute("SELECT action FROM audit_log WHERE actor = 'erick' ORDER BY id")]
    assert actions.count("device.command") == 2 and "device.session" in actions


def test_sin_comandos_solo_identifica(client, conn):
    r = client.post(f"/api/devices/{_id(conn, 'SIM-DIST-SW01')}/session", json={})
    assert r.status_code == 200 and [x["command"] for x in r.json["commands"]] == ["show version"]
    assert r.json["serial_number"] == "FOC1234SIM3"


def test_comando_bloqueado_no_abre_conexion(client, conn):
    dev = _id(conn, "SIM-CORE-RTR01")
    r = client.post(f"/api/devices/{dev}/session", json={"commands": ["show clock", "configure terminal"]})
    assert r.status_code == 403 and "No se abrió la conexión" in r.json["errors"][0]
    assert conn.execute("SELECT COUNT(*) FROM device_sessions").fetchone()[0] == 0
    row = conn.execute("SELECT result FROM audit_log WHERE action = 'device.command_blocked'").fetchone()
    assert row["result"] == "bloqueado"


@pytest.mark.parametrize("command", ["show clock ; reload", "show running-config", "write erase"])
def test_otros_bloqueos(client, conn, command):
    r = client.post(f"/api/devices/{_id(conn, 'SIM-CORE-RTR01')}/session", json={"commands": [command]})
    assert r.status_code == 403


def test_el_asistente_ia_no_se_conecta(conn):
    result, status = run_session(conn, _dev(conn, "SIM-CORE-RTR01"), ["show clock"], "asistente_ia")
    assert status == 403


def test_maximo_de_comandos(client, conn):
    r = client.post(f"/api/devices/{_id(conn, 'SIM-CORE-RTR01')}/session", json={"commands": ["show clock"] * 6})
    assert r.status_code == 400


def test_equipo_sin_modo_de_conexion(client, conn):
    r = client.post(f"/api/devices/{_id(conn, 'SIM-EDGE-FW01')}/session", json={})
    assert r.status_code == 400 and "no tiene modo de conexión" in r.json["errors"][0]


def test_ssh_sin_credenciales_en_env(client, conn, monkeypatch):
    monkeypatch.setattr(Config, "SSH_USERNAME", "")
    dev = _ssh_switch(conn)
    r = client.post(f"/api/devices/{dev['id']}/session", json={})
    assert r.status_code == 400 and "SSH_USERNAME" in r.json["errors"][0]


# ---------------------------------------------------------------------------
# 3. Trazabilidad: número de serie y llave SSH
# ---------------------------------------------------------------------------
def test_cambio_de_equipo_fisico_genera_alerta(client, conn):
    conn.execute("UPDATE devices SET serial_number = 'FOC9999OTRO' WHERE name = 'SIM-DIST-SW01'")
    conn.commit()
    r = client.post(f"/api/devices/{_id(conn, 'SIM-DIST-SW01')}/session", json={})
    assert any("EQUIPO FÍSICO DISTINTO" in w for w in r.json["warnings"])
    row = conn.execute("SELECT detail, result FROM audit_log WHERE action = 'device.serial_cambio'").fetchone()
    assert "FOC9999OTRO -> FOC1234SIM3" in row["detail"] and row["result"] == "alerta"
    assert _dev(conn, "SIM-DIST-SW01")["serial_number"] == "FOC1234SIM3"


def test_mismo_equipo_no_alerta(client, conn):
    dev = _id(conn, "SIM-DIST-SW01")
    client.post(f"/api/devices/{dev}/session", json={})
    r = client.post(f"/api/devices/{dev}/session", json={})
    assert r.json["warnings"] == []
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'device.serial_cambio'").fetchone()[0] == 0


def test_llave_ssh_se_fija_la_primera_vez(client, conn, fake, ssh_creds):
    dev = _ssh_switch(conn)
    fake(host_key_fp="SHA256:llaveA")
    r = client.post(f"/api/devices/{dev['id']}/session", json={})
    assert r.status_code == 200 and r.json["host_key_fp"] == "SHA256:llaveA"
    assert _dev(conn, "SIM-DIST-SW01")["host_key_fp"] == "SHA256:llaveA"
    assert conn.execute("SELECT 1 FROM audit_log WHERE action = 'device.hostkey_registrada'").fetchone()


def test_llave_ssh_distinta_aborta_sin_enviar_comandos(client, conn, fake, ssh_creds):
    dev = _ssh_switch(conn)
    conn.execute("UPDATE devices SET host_key_fp = 'SHA256:llaveA' WHERE id = ?", (dev["id"],))
    conn.commit()
    t = fake(host_key_fp="SHA256:llaveDelImpostor")
    r = client.post(f"/api/devices/{dev['id']}/session", json={"commands": ["show clock"]})
    assert r.status_code == 409 and "posible suplantación" in r.json["errors"][0]
    assert r.json["status"] == "fallida" and r.json["commands"] == [] and t.sent == []
    row = conn.execute("SELECT result FROM audit_log WHERE action = 'device.hostkey_cambio'").fetchone()
    assert row["result"] == "alerta"


def test_falla_de_conexion_queda_registrada(client, conn, fake, ssh_creds):
    dev = _ssh_switch(conn)
    fake(fail_open=True)
    r = client.post(f"/api/devices/{dev['id']}/session", json={})
    assert r.status_code == 502 and r.json["status"] == "fallida"
    assert "NetmikoTimeoutException" in r.json["error"]
    row = conn.execute("SELECT result FROM audit_log WHERE action = 'device.session'").fetchone()
    assert row["result"] == "alerta"


def test_la_contrasena_no_aparece_en_ningun_registro(client, conn, fake, ssh_creds):
    dev = _ssh_switch(conn)
    fake(host_key_fp="SHA256:llaveA")
    client.post(f"/api/devices/{dev['id']}/session", json={"commands": ["show clock"]})
    fake(fail_open=True)
    client.post(f"/api/devices/{dev['id']}/session", json={})
    dump = " ".join(str(tuple(r)) for t in ("audit_log", "device_sessions", "device_commands")
                    for r in conn.execute(f"SELECT * FROM {t}"))
    assert "ClaveDePrueba2026" not in dump


def test_equipo_ocupado(client, conn):
    dev = _dev(conn, "SIM-CORE-RTR01")
    lock = connector._lock_for(dev)
    lock.acquire()
    try:
        r = client.post(f"/api/devices/{dev['id']}/session", json={})
        assert r.status_code == 409 and "ocupado" in r.json["errors"][0]
    finally:
        lock.release()


def test_salida_grande_se_recorta_pero_la_huella_es_completa(client, conn, fake, ssh_creds):
    dev = _ssh_switch(conn)
    big = "x" * (connector.MAX_OUTPUT + 500)
    fake(outputs={"show version": IOS_VERSION, "show clock": big}, host_key_fp="SHA256:llaveA")
    cmd = client.post(f"/api/devices/{dev['id']}/session", json={"commands": ["show clock"]}).json["commands"][1]
    assert len(cmd["output"]) == connector.MAX_OUTPUT
    assert cmd["output_sha256"] == hashlib.sha256(big.encode()).hexdigest()


# ---------------------------------------------------------------------------
# 4. Parámetros reales de Netmiko (sin conectarse)
# ---------------------------------------------------------------------------
def test_parametros_consola_sin_contrasena(conn):
    conn.execute("UPDATE devices SET connection_mode = 'consola', platform = 'cisco_xe', "
                 "console_port = 'COM3' WHERE name = 'SIM-CORE-RTR01'")
    p = NetmikoTransport(_dev(conn, "SIM-CORE-RTR01"))._params()
    assert p["device_type"] == "cisco_ios_serial" and p["serial_settings"]["port"] == "COM3"
    assert p["password"] == "" and p["username"] == "" and "host" not in p


def test_parametros_ssh_toman_la_credencial_de_env(conn, ssh_creds):
    p = NetmikoTransport(_ssh_switch(conn))._params()
    assert p["device_type"] == "cisco_ios" and p["username"] == "noc_lectura" and p["host"] == "192.0.2.10"


# ---------------------------------------------------------------------------
# 5. Inventario: validación de los campos de conexión
# ---------------------------------------------------------------------------
def test_validacion_de_modo_plataforma_y_puerto(client, conn):
    fw, rtr = _id(conn, "SIM-EDGE-FW01"), _id(conn, "SIM-CORE-RTR01")
    r = client.put(f"/api/devices/{fw}", json={"connection_mode": "consola", "platform": "fortinet",
                                               "console_port": "COM3"})
    assert r.status_code == 400 and "solo está disponible para Cisco" in r.json["errors"][0]
    r = client.put(f"/api/devices/{rtr}", json={"platform": "huawei"})
    assert r.status_code == 400 and "no corresponde" in r.json["errors"][0]
    r = client.put(f"/api/devices/{rtr}", json={"connection_mode": "consola", "console_port": "COM3; del"})
    assert r.status_code == 400
    r = client.put(f"/api/devices/{rtr}", json={"connection_mode": "consola", "console_port": "com3"})
    assert r.status_code == 200 and r.json["console_port"] == "COM3"


def test_equipos_sim_listos_para_modo_simulado(conn):
    assert _dev(conn, "SIM-CORE-RTR01")["platform"] == "cisco_xe"
    assert _dev(conn, "SIM-DIST-SW01")["connection_mode"] == "simulado"
    assert _dev(conn, "SIM-EDGE-FW01")["connection_mode"] == "ninguno"


# ---------------------------------------------------------------------------
# 6. Consulta y permisos
# ---------------------------------------------------------------------------
def test_historial_y_detalle(client, conn):
    dev = _id(conn, "SIM-DIST-SW01")
    sid = client.post(f"/api/devices/{dev}/session", json={"commands": ["show inventory"]}).json["id"]
    rows = client.get(f"/api/devices/{dev}/sessions").json
    assert rows[0]["id"] == sid and rows[0]["commands_count"] == 2 and "output" not in rows[0]
    detail = client.get(f"/api/sessions/{sid}").json
    assert "FOC1234SIM3" in detail["commands"][1]["output"]
    assert client.get("/api/sessions/9999").status_code == 404


def test_auditor_consulta_pero_no_se_conecta(role_client, conn):
    c = role_client("auditor")
    dev = _id(conn, "SIM-DIST-SW01")
    assert c.get(f"/api/devices/{dev}/sessions").status_code == 200
    assert c.post(f"/api/devices/{dev}/session", json={}).status_code == 403


# ---------------------------------------------------------------------------
# 7. Migración: una base v0.3.0 recibe las columnas y tablas nuevas
# ---------------------------------------------------------------------------
def test_migracion_desde_v030(conn):
    conn.execute("DROP TABLE device_commands")
    conn.execute("DROP TABLE device_sessions")
    for col in ("connection_mode", "platform", "console_port", "serial_number", "detected_model",
                "detected_version", "host_key_fp", "last_identified_at"):
        conn.execute(f"ALTER TABLE devices DROP COLUMN {col}")
    conn.commit()
    init_db(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(devices)")}
    assert {"connection_mode", "serial_number", "host_key_fp"} <= cols
    assert _dev(conn, "SIM-CORE-RTR01")["connection_mode"] == "ninguno"     # valor por defecto
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'device_sessions'").fetchone()
