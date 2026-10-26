"""
Pruebas de la Fase 10.1: versiones de configuración con diferencias.

En modo simulado, la configuración sale de samples/cli/<plataforma>/show_running-config.txt
y refleja el inventario (hostname y descripciones de interfaces): editar una
descripción en el NOC "cambia" el equipo simulado.
"""
import hashlib
from pathlib import Path

import pytest

import app.connector as connector
from app.configversions import mask_secrets, normalize, prepare
from app.connector import run_session
from app.console import check

SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "cli"
XE_RUN = (SAMPLES / "cisco_xe" / "show_running-config.txt").read_text(encoding="utf-8")
XE_VERSION = (SAMPLES / "cisco_xe" / "show_version.txt").read_text(encoding="utf-8")


def _dev(conn, name="SIM-CORE-RTR01"):
    return conn.execute("SELECT * FROM devices WHERE name = ?", (name,)).fetchone()


def _capture(client, conn, name="SIM-CORE-RTR01", note=""):
    return client.post(f"/api/devices/{_dev(conn, name)['id']}/configs", json={"note": note})


def _set_description(client, conn, iface, text, name="SIM-CORE-RTR01"):
    dev_id = _dev(conn, name)["id"]
    r = client.post(f"/api/devices/{dev_id}/interfaces", json={"name": iface, "status": "down", "description": text})
    assert r.status_code == 201, r.json


# ---------------------------------------------------------------------------
# 1. Secretos ocultos
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("line, expected", [
    ("enable secret 9 $9$abcDEF$xyz", "enable secret 9 <oculto>"),
    ("enable password cisco123", "enable password <oculto>"),
    ("username noc privilege 15 secret 9 $9$aa$bb", "username noc privilege 15 secret 9 <oculto>"),
    ("username viejo password 7 0822455D0A16", "username viejo password 7 <oculto>"),
    ("snmp-server community publica RO", "snmp-server community <oculto> RO"),
    (" password 7 045802150C2E", " password 7 <oculto>"),
    (" key-string 7 1511021F0725", " key-string 7 <oculto>"),
    ("ntp authentication-key 1 md5 104D000A0618 7", "ntp authentication-key 1 md5 <oculto> 7"),
    ("    set password ENC SH2nlSm9QL9tapcHPXIqAXvX", "    set password ENC <oculto>"),          # Fortinet
    (" local-user admin password irreversible-cipher $1c$Zx$", " local-user admin password irreversible-cipher <oculto>"),
])
def test_oculta_secretos(line, expected):
    text, n = mask_secrets(line)
    assert text == expected and n == 1


@pytest.mark.parametrize("line", [
    "service password-encryption", "no service password-encryption", "key chain OSPF-KEYS",
    "hostname SIM-CORE-RTR01", "logging host 192.168.100.10 transport udp port 5514",
])
def test_no_toca_lo_que_no_es_secreto(line):
    assert mask_secrets(line) == (line, 0)


def test_llave_privada_completa():
    text, n = mask_secrets("-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nAAAA\n-----END RSA PRIVATE KEY-----")
    assert "MIIEow" not in text and n == 2 and text.startswith("-----BEGIN")


def test_ocultar_dos_veces_no_cambia_nada():
    once, _ = mask_secrets(XE_RUN)
    assert mask_secrets(once) == (once, 0)


# ---------------------------------------------------------------------------
# 2. Normalización: lo que cambia solo con el tiempo no crea versiones
# ---------------------------------------------------------------------------
def test_normaliza_lineas_volatiles():
    a = "Building configuration...\n\nCurrent configuration : 2718 bytes\n!\n! Last configuration change at 19:20:41 COT\nhostname R1\nend"
    b = "Building configuration...\r\n\r\nCurrent configuration : 2730 bytes\r\n!\r\n! Last configuration change at 20:01:02 COT\r\nhostname R1   \r\nend\r\n"
    assert normalize(a) == normalize(b) == "!\nhostname R1\nend"


def test_prepare_quita_secretos_y_fechas():
    clean, masked = prepare(XE_RUN)
    assert masked == 3 and "$9$" not in clean and "SIM-comunidad" not in clean
    assert "Last configuration change" not in clean and "Building configuration" not in clean


# ---------------------------------------------------------------------------
# 3. Captura (API)
# ---------------------------------------------------------------------------
def test_primera_version(client, conn):
    r = _capture(client, conn, note="Línea base")
    assert r.status_code == 201 and r.json["changed"] and r.json["previous"] is None
    v = r.json["version"]
    assert v["version_no"] == 1 and v["masked"] == 3 and v["serial_number"] == "FGL2601SIM1"
    assert v["note"] == "Línea base" and v["added"] is None and "content" not in v
    row = conn.execute("SELECT content, sha256 FROM config_versions").fetchone()
    assert "<oculto>" in row["content"] and "$9$" not in row["content"]
    assert row["sha256"] == hashlib.sha256(row["content"].encode()).hexdigest()
    audit = conn.execute("SELECT actor, detail FROM audit_log WHERE action = 'config.capture'").fetchone()
    assert audit["actor"] == "tester" and "versión inicial v1" in audit["detail"]


def test_el_historial_de_comandos_tampoco_guarda_secretos(client, conn):
    _capture(client, conn)
    cmd = conn.execute("SELECT output, output_sha256 FROM device_commands "
                       "WHERE command = 'show running-config'").fetchone()
    assert "$9$" not in cmd["output"] and "SIM-comunidad" not in cmd["output"]
    assert cmd["output_sha256"] == hashlib.sha256(cmd["output"].encode()).hexdigest()


def test_sin_cambios_no_crea_version(client, conn):
    _capture(client, conn)
    r = _capture(client, conn)
    assert r.status_code == 200 and r.json["changed"] is False
    assert "Sin cambios desde la versión 1" in r.json["message"]
    assert conn.execute("SELECT COUNT(*) FROM config_versions").fetchone()[0] == 1


def test_cambio_crea_version_y_alerta(client, conn):
    _capture(client, conn)
    _set_description(client, conn, "GigabitEthernet0/0/1", "Enlace a ISP de respaldo")
    r = _capture(client, conn)
    assert r.status_code == 201 and r.json["version"]["version_no"] == 2
    assert r.json["version"]["added"] == 1 and r.json["version"]["removed"] == 0
    assert "CAMBIÓ" in r.json["message"]
    a = conn.execute("SELECT detail, result FROM audit_log WHERE action = 'config.changed'").fetchone()
    assert a["result"] == "alerta" and "v2" in a["detail"] and "+1 -0" in a["detail"]


def test_lista_y_contador_en_inventario(client, conn):
    _capture(client, conn)
    _set_description(client, conn, "GigabitEthernet0/0/2", "Reserva")
    _capture(client, conn)
    dev_id = _dev(conn)["id"]
    rows = client.get(f"/api/devices/{dev_id}/configs").json
    assert [v["version_no"] for v in rows] == [2, 1] and all("content" not in v for v in rows)
    d = next(x for x in client.get("/api/devices").json if x["id"] == dev_id)
    assert d["config_count"] == 2
    full = client.get(f"/api/configs/{rows[0]['id']}").json
    assert "description Reserva" in full["content"]


@pytest.mark.parametrize("note, field", [("x" * 201, "máximo 200")])
def test_nota_demasiado_larga(client, conn, note, field):
    r = _capture(client, conn, note=note)
    assert r.status_code == 400 and field in r.json["errors"][0]


def test_equipo_sin_conexion_o_sin_plataforma(client, conn):
    assert _capture(client, conn, "SIM-EDGE-FW01").status_code == 400
    conn.execute("UPDATE devices SET platform = NULL WHERE name = 'SIM-CORE-RTR01'")
    conn.commit()
    r = _capture(client, conn)
    assert r.status_code == 400 and "plataforma" in r.json["errors"][0]


def test_salida_que_no_es_configuracion(client, conn, monkeypatch):
    monkeypatch.setattr(connector.SimulatedTransport, "send",
                        lambda self, c: XE_VERSION if c == "show version" else "% Invalid input")
    r = _capture(client, conn)
    assert r.status_code == 502 and "no parece una configuración" in r.json["errors"][0]
    assert conn.execute("SELECT COUNT(*) FROM config_versions").fetchone()[0] == 0


def test_otro_equipo_fisico_avisa(client, conn, monkeypatch):
    _capture(client, conn)
    real_send = connector.SimulatedTransport.send
    monkeypatch.setattr(connector.SimulatedTransport, "send", lambda self, c: (
        real_send(self, c).replace("FGL2601SIM1", "FGL9999SIM9") if c == "show version" else real_send(self, c)))
    r = _capture(client, conn)
    assert any("OTRO equipo físico" in w for w in r.json["warnings"])


def test_borrar_equipo_conserva_versiones(client, conn):
    _capture(client, conn)
    dev_id = _dev(conn)["id"]
    assert client.delete(f"/api/devices/{dev_id}").status_code in (200, 204)
    row = conn.execute("SELECT device_id, device_name FROM config_versions").fetchone()
    assert row["device_id"] is None and row["device_name"] == "SIM-CORE-RTR01"


# ---------------------------------------------------------------------------
# 4. Diferencias
# ---------------------------------------------------------------------------
def test_diff_muestra_la_linea_agregada(client, conn):
    _capture(client, conn)
    _set_description(client, conn, "GigabitEthernet0/0/1", "Enlace a ISP de respaldo")
    _capture(client, conn)
    ids = [v["id"] for v in client.get(f"/api/devices/{_dev(conn)['id']}/configs").json]
    r = client.get(f"/api/configs/diff?from={ids[1]}&to={ids[0]}")
    assert r.status_code == 200 and r.json["added"] == 1 and r.json["removed"] == 0
    assert "+ description Enlace a ISP de respaldo" in r.json["lines"]
    assert r.json["lines"][0].startswith("--- SIM-CORE-RTR01 v1") and not r.json["identical"]


def test_diff_identico_y_errores(client, conn):
    _capture(client, conn)
    vid = conn.execute("SELECT id FROM config_versions").fetchone()[0]
    assert client.get(f"/api/configs/diff?from={vid}&to={vid}").json["identical"] is True
    assert client.get("/api/configs/diff?from=x&to=1").status_code == 400
    assert client.get(f"/api/configs/diff?from={vid}&to=999").status_code == 404
    assert client.get("/api/configs/999").status_code == 404


def test_diff_entre_dos_equipos_avisa(client, conn):
    _capture(client, conn)
    _capture(client, conn, "SIM-DIST-SW01")
    a, b = [r[0] for r in conn.execute("SELECT id FROM config_versions ORDER BY id")]
    r = client.get(f"/api/configs/diff?from={a}&to={b}").json
    assert "DOS equipos distintos" in r["warnings"][0] and r["added"] > 0


# ---------------------------------------------------------------------------
# 5. Seguridad: política, roles y evidencia
# ---------------------------------------------------------------------------
def test_running_config_sigue_bloqueado_en_la_sesion_normal(conn):
    result, status = run_session(conn, _dev(conn), ["show running-config"], "tester")
    assert status == 403 and "secretos ocultos" in result["errors"][1]


def test_captura_solo_acepta_su_comando():
    assert check("Cisco", "show running-config", "op", capture=True)[0]
    assert check("Huawei", "display current-configuration", "op", capture=True)[0]
    assert not check("Cisco", "write erase", "op", capture=True)[0]
    assert not check("Cisco", "show startup-config", "op", capture=True)[0]


def test_la_ia_no_captura(conn):
    result, status = run_session(conn, _dev(conn), ["show running-config"], "asistente_ia",
                                 sanitize=lambda raw: prepare(raw)[0])
    assert status == 403 and "agente de IA" in result["errors"][1]


def test_auditor_consulta_pero_no_captura(client, role_client, conn):
    _capture(client, conn)
    aud = role_client("auditor")
    dev_id = _dev(conn)["id"]
    assert aud.post(f"/api/devices/{dev_id}/configs", json={}).status_code == 403
    rows = aud.get(f"/api/devices/{dev_id}/configs").json
    assert len(rows) == 1 and aud.get(f"/api/configs/{rows[0]['id']}").status_code == 200


def test_operador_captura(role_client, conn):
    r = _capture(role_client("operador", "erick"), conn)
    assert r.status_code == 201 and r.json["version"]["captured_by"] == "erick"


def test_versiones_no_se_modifican_ni_borran(client, conn):
    _capture(client, conn)
    with pytest.raises(Exception, match="no se pueden modificar"):
        conn.execute("UPDATE config_versions SET content = 'hostname OTRO'")
    with pytest.raises(Exception, match="no se pueden borrar"):
        conn.execute("DELETE FROM config_versions")
