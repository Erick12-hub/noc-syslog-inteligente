"""
Pruebas de la Fase 8.4: interfaces de cada equipo del inventario.

Equipos SIMULADOS de app/seed.py (IP de documentación, RFC 5737):
    SIM-CORE-RTR01  192.0.2.1      Cisco
    SIM-EDGE-FW01   198.51.100.1   Fortinet
    SIM-BR-RTR02    198.51.100.20  Huawei
"""
import pytest

from app.db import init_db
from app.ingest import ingest
from app.interfaces import validate_interface_name, normalize_for_vendor


def _dev(conn, name):
    return conn.execute("SELECT id FROM devices WHERE name = ?", (name,)).fetchone()["id"]


def _add(c, device_id, name, status="up", description=None):
    return c.post(f"/api/devices/{device_id}/interfaces",
                  json={"name": name, "status": status, "description": description})


LINK_DOWN = ("<187>1: *Oct  5 10:15:42.551: SIM-CORE-RTR01 %LINK-3-UPDOWN: "
             "Interface {iface}, changed state to down")


def _flags(conn, event_id):
    return (conn.execute("SELECT flags FROM syslog_events WHERE id = ?", (event_id,)).fetchone()["flags"] or "").split(",")


# ---------------------------------------------------------------------------
# 1. Sintaxis del nombre SEGÚN EL FABRICANTE
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("vendor, name", [
    ("Cisco", "GigabitEthernet0/0/1"), ("Cisco", "GigabitEthernet0/0/1.100"), ("Cisco", "Vlan10"),
    ("Cisco", "Port-channel1"), ("Huawei", "Vlanif10"), ("Huawei", "Eth-Trunk1"),
    ("Huawei", "XGigabitEthernet0/0/1"), ("Fortinet", "port1"), ("Fortinet", "wan1"),
    ("Fortinet", "internal"), ("Otro", "eth0"),
])
def test_nombres_validos(vendor, name):
    assert validate_interface_name(vendor, name) == []


@pytest.mark.parametrize("vendor, name", [
    ("Cisco", "port1"),                          # nombre de FortiGate en un Cisco
    ("Cisco", "GigabitEthernet"),                # sin número
    ("Huawei", "wan1"),
    ("Fortinet", "GigabitEthernet0/1"),          # nombre de Cisco en un FortiGate
    ("Fortinet", "nombre-demasiado-largo"),      # FortiOS: máximo 15 caracteres
    ("Cisco", "Gi0/1; reload"),                  # intento de inyección
    ("Otro", "<script>"),
])
def test_nombres_invalidos(vendor, name):
    assert validate_interface_name(vendor, name)


def test_nombre_corto_se_normaliza_solo_en_cisco_y_huawei():
    assert normalize_for_vendor("Cisco", "Gi0/1") == "GigabitEthernet0/1"
    assert normalize_for_vendor("Huawei", "GE0/0/1") == "GigabitEthernet0/0/1"
    assert normalize_for_vendor("Cisco", "gigabitethernet0/1") == "GigabitEthernet0/1"
    assert normalize_for_vendor("Cisco", "te1/0/1") == "TenGigabitEthernet1/0/1"
    assert normalize_for_vendor("Huawei", "vlanif10") == "Vlanif10"
    assert normalize_for_vendor("Fortinet", "port1") == "port1"


# ---------------------------------------------------------------------------
# 2. API
# ---------------------------------------------------------------------------
def test_registrar_interfaz_normaliza_y_audita(role_client, conn):
    c = role_client("operador", "erick")
    dev = _dev(conn, "SIM-CORE-RTR01")
    r = _add(c, dev, "Gi0/0/1", "up", "Enlace a SIM-DIST-SW01")
    assert r.status_code == 201 and r.json["name"] == "GigabitEthernet0/0/1"
    row = conn.execute("SELECT actor, detail FROM audit_log WHERE action = 'interface.create'").fetchone()
    assert row["actor"] == "erick" and "SIM-CORE-RTR01 GigabitEthernet0/0/1" in row["detail"]
    listed = c.get(f"/api/devices/{dev}/interfaces").json
    assert [i["name"] for i in listed["rows"]] == ["GigabitEthernet0/0/1"] and "Gi0/1" in listed["example"]


def test_interfaz_repetida_sin_importar_mayusculas(client, conn):
    dev = _dev(conn, "SIM-CORE-RTR01")
    assert _add(client, dev, "GigabitEthernet0/0/1").status_code == 201
    r = _add(client, dev, "gigabitethernet0/0/1")
    assert r.status_code == 409 and "ya tiene la interfaz" in r.json["errors"][0]


def test_errores_juntos(client, conn):
    r = client.post(f"/api/devices/{_dev(conn, 'SIM-EDGE-FW01')}/interfaces",
                    json={"name": "GigabitEthernet0/1", "status": "prendida", "description": "x" * 101})
    assert r.status_code == 400 and len(r.json["errors"]) == 3     # nombre, estado y descripción


def test_editar_y_eliminar_quedan_auditados(client, conn):
    dev = _dev(conn, "SIM-EDGE-FW01")
    iid = _add(client, dev, "wan1", "up").json["id"]
    r = client.put(f"/api/devices/{dev}/interfaces/{iid}", json={"status": "down"})
    assert r.status_code == 200 and r.json["status"] == "down"
    assert client.delete(f"/api/devices/{dev}/interfaces/{iid}").status_code == 200
    actions = [r["action"] for r in conn.execute(
        "SELECT action FROM audit_log WHERE entity = 'interfaces' ORDER BY id")]
    assert actions == ["interface.create", "interface.update", "interface.delete"]


def test_no_se_edita_una_interfaz_por_medio_de_otro_equipo(client, conn):
    iid = _add(client, _dev(conn, "SIM-EDGE-FW01"), "wan1").json["id"]
    other = _dev(conn, "SIM-CORE-RTR01")
    assert client.put(f"/api/devices/{other}/interfaces/{iid}", json={"status": "down"}).status_code == 404
    assert client.delete(f"/api/devices/{other}/interfaces/{iid}").status_code == 404


def test_equipo_inexistente(client):
    assert client.get("/api/devices/9999/interfaces").status_code == 404
    assert _add(client, 9999, "port1").status_code == 404


def test_eliminar_equipo_elimina_sus_interfaces(client, conn):
    dev = _dev(conn, "SIM-EDGE-FW01")
    _add(client, dev, "wan1"), _add(client, dev, "internal")
    assert client.delete(f"/api/devices/{dev}").status_code == 200
    assert conn.execute("SELECT COUNT(*) FROM interfaces WHERE device_id = ?", (dev,)).fetchone()[0] == 0
    detail = conn.execute("SELECT detail FROM audit_log WHERE action = 'device.delete'").fetchone()["detail"]
    assert "interfaces=2" in detail


def test_listado_de_equipos_trae_el_contador(client, conn):
    dev = _dev(conn, "SIM-CORE-RTR01")
    _add(client, dev, "Gi0/0/0"), _add(client, dev, "Gi0/0/1")
    rows = {d["name"]: d for d in client.get("/api/devices").json}
    assert rows["SIM-CORE-RTR01"]["interface_count"] == 2 and rows["SIM-EDGE-FW01"]["interface_count"] == 0


def test_auditor_consulta_pero_no_modifica(role_client, conn):
    c = role_client("auditor")
    dev = _dev(conn, "SIM-CORE-RTR01")
    assert c.get(f"/api/devices/{dev}/interfaces").status_code == 200
    assert _add(c, dev, "Gi0/0/1").status_code == 403
    html = c.get("/inventario").get_data(as_text=True)
    assert 'data-can-edit="0"' in html and 'id="btn-new"' not in html


def test_operador_ve_los_controles(role_client):
    html = role_client("operador").get("/inventario").get_data(as_text=True)
    assert 'data-can-edit="1"' in html and 'id="btn-new"' in html


# ---------------------------------------------------------------------------
# 3. Ingesta: marca 'interfaz_desconocida'
# ---------------------------------------------------------------------------
def test_sin_interfaces_registradas_no_se_marca(conn):
    r = ingest(conn, LINK_DOWN.format(iface="GigabitEthernet0/0/9"), "192.0.2.1", "simulador")
    assert "interfaz_desconocida" not in r["flags"]


def test_interfaz_registrada_no_se_marca(client, conn):
    _add(client, _dev(conn, "SIM-CORE-RTR01"), "GigabitEthernet0/0/2")
    # El mensaje usa el nombre CORTO y otra capitalización: igual es la misma interfaz
    r = ingest(conn, LINK_DOWN.format(iface="Gi0/0/2"), "192.0.2.1", "simulador")
    assert "interfaz_desconocida" not in _flags(conn, r["id"])


def test_subinterfaz_de_una_registrada_no_se_marca(client, conn):
    _add(client, _dev(conn, "SIM-CORE-RTR01"), "GigabitEthernet0/0/1")
    r = ingest(conn, LINK_DOWN.format(iface="GigabitEthernet0/0/1.100"), "192.0.2.1", "simulador")
    assert "interfaz_desconocida" not in r["flags"]


def test_interfaz_no_registrada_se_marca_y_audita(client, conn):
    _add(client, _dev(conn, "SIM-CORE-RTR01"), "GigabitEthernet0/0/1")
    r = ingest(conn, LINK_DOWN.format(iface="GigabitEthernet0/0/9"), "192.0.2.1", "simulador")
    assert "interfaz_desconocida" in _flags(conn, r["id"])
    row = conn.execute("SELECT detail, result FROM audit_log WHERE action = 'syslog.sospechoso'").fetchone()
    assert "interfaz_desconocida" in row["detail"] and row["result"] == "alerta"


def test_fortigate_compara_sus_propios_nombres(client, conn):
    _add(client, _dev(conn, "SIM-EDGE-FW01"), "wan1")
    raw = ('<188>date=2026-10-05 time=23:52:10 devname="SIM-EDGE-FW01" logid="0000000013" type="traffic" '
           'level="warning" srcip=203.0.113.200 srcport=51520 srcintf="{i}" dstport=3389')
    ok = ingest(conn, raw.format(i="wan1"), "198.51.100.1", "simulador")
    bad = ingest(conn, raw.format(i="wan9"), "198.51.100.1", "simulador")
    assert "interfaz_desconocida" not in ok["flags"] and "interfaz_desconocida" in bad["flags"]


def test_filtro_de_eventos_por_la_marca(client, conn):
    _add(client, _dev(conn, "SIM-CORE-RTR01"), "GigabitEthernet0/0/1")
    ingest(conn, LINK_DOWN.format(iface="GigabitEthernet0/0/9"), "192.0.2.1", "simulador")
    r = client.get("/api/events?flag=interfaz_desconocida")
    assert r.status_code == 200 and len(r.json) == 1 and r.json[0]["interface"] == "GigabitEthernet0/0/9"


def test_dos_interfaces_distintas_no_se_agrupan(conn):
    # Hallazgo de la prueba en vivo (8.4): la huella cambiaba los números por '#'
    # y "Gi0/0/1 down" + "Gi0/0/9 down" quedaban como UN solo evento repetido
    a = ingest(conn, LINK_DOWN.format(iface="GigabitEthernet0/0/1"), "192.0.2.1", "simulador")
    b = ingest(conn, LINK_DOWN.format(iface="GigabitEthernet0/0/9"), "192.0.2.1", "simulador")
    assert not b["duplicate"] and a["id"] != b["id"]


def test_la_misma_interfaz_si_se_agrupa(conn):
    a = ingest(conn, LINK_DOWN.format(iface="GigabitEthernet0/0/1"), "192.0.2.1", "simulador")
    b = ingest(conn, LINK_DOWN.format(iface="GigabitEthernet0/0/1"), "192.0.2.1", "simulador")   # se repite
    assert b["duplicate"] and b["id"] == a["id"]


def test_interfaz_no_registrada_no_se_esconde_como_repeticion(client, conn):
    _add(client, _dev(conn, "SIM-CORE-RTR01"), "GigabitEthernet0/0/1")
    ingest(conn, LINK_DOWN.format(iface="GigabitEthernet0/0/1"), "192.0.2.1", "simulador")
    r = ingest(conn, LINK_DOWN.format(iface="GigabitEthernet0/0/9"), "192.0.2.1", "simulador")
    assert not r["duplicate"] and "interfaz_desconocida" in _flags(conn, r["id"])


# ---------------------------------------------------------------------------
# 4. Migración: una base v0.2.1 recibe la tabla nueva al arrancar
# ---------------------------------------------------------------------------
def test_migracion_crea_la_tabla(conn):
    conn.execute("DROP TABLE interfaces")
    conn.commit()
    init_db(conn)
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'interfaces'").fetchone()
