"""
Pruebas de la Fase 9.2: configuración base desde cero para el laboratorio.

Lo más importante: en modo PRÉSTAMO la configuración no lleva NINGUNA
credencial ni se guarda (los equipos son prestados y rotan).
"""
import pytest

from app.configgen import CREDENTIAL_WORDS, _validate_baseline, baseline

ROUTER = {"role": "router", "mode": "prestamo", "hostname": "LAB-RTR01", "mgmt_ip": "192.168.100.1",
          "prefix": "24", "noc_ip": "192.168.100.10", "port": "5514", "severity": "6"}
SWITCH = {**ROUTER, "role": "switch", "hostname": "LAB-SW01", "mgmt_ip": "192.168.100.2",
          "gateway": "192.168.100.1"}


def _text(args, kind="pegar"):
    return "\n".join(b["text"] for b in baseline(_validate_baseline(args)[0]) if b["kind"] == kind)


# ---------------------------------------------------------------------------
# 1. Préstamo: sin credenciales y sin guardar
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("args", [ROUTER, SWITCH], ids=["router", "switch"])
def test_prestamo_sin_credenciales_ni_guardar(args):
    full = "\n".join(b["text"] for b in baseline(_validate_baseline(args)[0])).lower()
    for word in CREDENTIAL_WORDS:
        assert word not in full, f"'{word}' no debe aparecer en una configuración de préstamo"
    assert "line vty" not in full                     # sin acceso remoto


def test_fijo_agrega_ssh_con_marcadores_y_guarda():
    blocks = baseline(_validate_baseline({**ROUTER, "mode": "fijo"})[0])
    ssh = next(b for b in blocks if b["title"].startswith("2b"))
    assert ssh["kind"] == "manual"                    # se edita ANTES de pegar
    assert "<USUARIO>" in ssh["text"] and "<CONTRASEÑA>" in ssh["text"]
    assert "ip ssh version 2" in ssh["text"] and "transport input ssh" in ssh["text"]
    assert "write memory" in _text({**ROUTER, "mode": "fijo"})


# ---------------------------------------------------------------------------
# 2. Contenido del router y del switch
# ---------------------------------------------------------------------------
def test_router_es_servidor_ntp_y_envia_syslog():
    text = _text(ROUTER)
    assert "hostname LAB-RTR01" in text
    assert "interface GigabitEthernet0/0/0" in text and "ip address 192.168.100.1 255.255.255.0" in text
    assert "ntp master 3" in text and "clock timezone COT -5 0" in text
    assert "logging host 192.168.100.10 transport udp port 5514" in text
    assert "logging trap informational" in text and "logging source-interface GigabitEthernet0/0/0" in text
    assert "service timestamps log datetime msec localtime show-timezone year" in text
    # La hora se pone a mano antes (el router no tiene de dónde sacarla)
    assert any(b["title"].startswith("1.") and "clock set" in b["text"]
               for b in baseline(_validate_baseline(ROUTER)[0]))


def test_switch_usa_vlan1_puerta_de_enlace_y_ntp_del_router():
    text = _text(SWITCH)
    assert "interface Vlan1" in text and "ip default-gateway 192.168.100.1" in text
    assert "ntp server 192.168.100.1" in text and "ntp master" not in text
    assert "logging source-interface Vlan1" in text
    clean = _text(SWITCH, "manual")
    assert "delete flash:vlan.dat" in clean           # el 2960 guarda las VLAN aparte


def test_bloques_en_orden_y_limpieza_final():
    titles = [b["title"] for b in baseline(_validate_baseline(ROUTER)[0])]
    assert titles[0].startswith("0.") and titles[-1].startswith("4.")
    last = baseline(_validate_baseline(ROUTER)[0])[-1]["text"]
    assert "write erase" in last and "reload" in last


def test_la_configuracion_se_puede_pegar_linea_por_linea():
    for line in _text(ROUTER).splitlines() + _text(SWITCH).splitlines():
        assert len(line) <= 90                        # PuTTY y la consola de 9600 baudios
        assert "\t" not in line
        assert line == line.rstrip()


def test_verificacion_incluye_ping_y_mensaje_de_prueba():
    text = _text(ROUTER, "verificar")
    assert "ping 192.168.100.10" in text and 'send log 6 "Prueba NOC desde LAB-RTR01"' in text


# ---------------------------------------------------------------------------
# 3. Validación de parámetros (nada se "cuela" en la configuración)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("change, message", [
    ({"hostname": "LAB_RTR01"}, "Hostname inválido"),            # IOS no acepta "_"
    ({"hostname": "LAB-RTR01\nreload"}, "Hostname inválido"),     # intento de inyección
    ({"mgmt_ip": "192.168.100.300"}, "IP de gestión"),
    ({"noc_ip": "10.0.0.10"}, "no está en la red"),
    ({"noc_ip": "192.168.100.1"}, "no pueden ser iguales"),
    ({"mgmt_ip": "192.168.100.0"}, "dirección de red"),
    ({"prefix": "31"}, "Máscara inválida"),
    ({"prefix": "255.0.255.0"}, "Máscara inválida"),              # máscara no contigua
    ({"mgmt_if": "Gi0/0/0; reload"}, "Interfaz de gestión inválida"),
    ({"mgmt_if": "Vlan1"}, "interfaz física"),                    # router con Vlan
    ({"role": "firewall"}, "Rol inválido"),
    ({"mode": "temporal"}, "Modo inválido"),
    ({"severity": "9"}, "Severidad inválida"),
])
def test_parametros_invalidos(change, message):
    _, errors = _validate_baseline({**ROUTER, **change})
    assert any(message in e for e in errors), errors


def test_errores_de_red_junto_con_otros_errores():
    # Hallazgo de la revisión visual: con el hostname mal no se veía que el PC estaba fuera de la red
    _, errors = _validate_baseline({**ROUTER, "hostname": "LAB_RTR 01", "noc_ip": "10.0.0.10"})
    assert len(errors) == 2 and any("no está en la red" in e for e in errors)


@pytest.mark.parametrize("mask, prefix", [("24", 24), ("/24", 24), ("255.255.255.0", 24),
                                          ("255.255.255.128", 25), ("255.255.0.0", 16)])
def test_mascara_como_prefijo_o_decimal(mask, prefix):
    v, errors = _validate_baseline({**ROUTER, "prefix": mask})
    assert errors == [] and v["prefix"] == prefix


def test_direccionamiento_manual_de_un_equipo_real():
    # Datos que entrega el laboratorio: otra red, otra interfaz y máscara decimal
    args = {**SWITCH, "hostname": "SW-PISO3", "mgmt_if": "vlan10", "mgmt_ip": "10.20.30.40",
            "prefix": "255.255.255.0", "gateway": "10.20.30.1", "noc_ip": "10.20.30.200", "port": "514"}
    v, errors = _validate_baseline(args)
    assert errors == []
    text = _text(args)
    assert "interface Vlan10" in text and "ip address 10.20.30.40 255.255.255.0" in text
    assert "logging source-interface Vlan10" in text and "ip default-gateway 10.20.30.1" in text
    assert "logging host 10.20.30.200 transport udp port 514" in text and "ntp server 10.20.30.1" in text
    # La VLAN 10 se crea ANTES de su interfaz y los puertos de acceso quedan en ella
    assert text.index("vlan 10") < text.index("interface Vlan10")
    assert " switchport access vlan 10" in text


def test_router_con_otra_interfaz_y_nombre_corto():
    v, errors = _validate_baseline({**ROUTER, "mgmt_if": "gi0/0/1"})
    assert errors == [] and v["mgmt_if"] == "GigabitEthernet0/0/1"
    assert "interface GigabitEthernet0/0/1" in _text({**ROUTER, "mgmt_if": "gi0/0/1"})


def test_switch_con_interfaz_fisica_se_rechaza():
    _, errors = _validate_baseline({**SWITCH, "mgmt_if": "FastEthernet0/1"})
    assert any("interfaz Vlan" in e for e in errors)


def test_switch_sin_puerta_de_enlace():
    _, errors = _validate_baseline({**SWITCH, "gateway": ""})
    assert any("puerta de enlace" in e for e in errors)


# ---------------------------------------------------------------------------
# 4. API
# ---------------------------------------------------------------------------
def test_api_genera_y_audita(role_client, conn):
    c = role_client("operador", "erick")
    r = c.get("/api/config/baseline", query_string=ROUTER)
    assert r.status_code == 200 and r.json["platform"] == "cisco_xe" and len(r.json["blocks"]) == 5
    row = conn.execute("SELECT actor, detail FROM audit_log WHERE action = 'config.baseline'").fetchone()
    assert row["actor"] == "erick" and "router prestamo LAB-RTR01" in row["detail"]


def test_api_todos_los_errores_juntos(client):
    r = client.get("/api/config/baseline", query_string={**ROUTER, "hostname": "x y", "port": "0"})
    assert r.status_code == 400 and len(r.json["errors"]) == 2


def test_api_coherencia_con_el_inventario(client, conn):
    rtr = conn.execute("SELECT id FROM devices WHERE name = 'SIM-CORE-RTR01'").fetchone()["id"]
    fw = conn.execute("SELECT id FROM devices WHERE name = 'SIM-EDGE-FW01'").fetchone()["id"]
    r = client.get("/api/config/baseline", query_string={**ROUTER, "device_id": rtr})
    assert r.status_code == 400 and "no coincide con la del inventario" in r.json["errors"][0]
    r = client.get("/api/config/baseline", query_string={**ROUTER, "device_id": fw})
    assert r.status_code == 400 and "es Fortinet" in r.json["errors"][0]


def test_auditor_no_genera_configuraciones(role_client):
    assert role_client("auditor").get("/api/config/baseline", query_string=ROUTER).status_code == 403


# ---------------------------------------------------------------------------
# 5. Correcciones del 9.1
# ---------------------------------------------------------------------------
def test_mensaje_de_puerto_inexistente_en_espanol(conn):
    from app.connector import NetmikoTransport
    conn.execute("UPDATE devices SET connection_mode = 'consola', console_port = 'COM3' WHERE name = 'SIM-CORE-RTR01'")
    dev = conn.execute("SELECT * FROM devices WHERE name = 'SIM-CORE-RTR01'").fetchone()
    t = NetmikoTransport(dev)
    msg = t._friendly_error(ValueError("device COM3 not found. available devices are: "))
    assert "no existe en este PC" in msg and "ninguno" in msg and "cable de consola" in msg
    msg = t._friendly_error(PermissionError("could not open port 'COM3': PermissionError(13, 'Access is denied.')"))
    assert "PuTTY" in msg


def test_sesion_simulada_no_repite_la_palabra(client, conn):
    dev = conn.execute("SELECT id FROM devices WHERE name = 'SIM-DIST-SW01'").fetchone()["id"]
    client.post(f"/api/devices/{dev}/session", json={})
    detail = conn.execute("SELECT detail FROM audit_log WHERE action = 'device.session'").fetchone()["detail"]
    assert "simulado simulado" not in detail
