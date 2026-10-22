"""
Pruebas de la Fase 9.3: interfaces reales leídas del equipo.

Se usan las salidas de ejemplo de samples/cli/ (formato real de un C8200 y un
2960) en modo simulado, y textos de ejemplo de Huawei y Fortinet.
"""
from pathlib import Path

import pytest

import app.connector as connector
from app.ingest import ingest
from app.interfaces import apply_sync, parse_interfaces

SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "cli"
XE_BRIEF = (SAMPLES / "cisco_xe" / "show_ip_interface_brief.txt").read_text(encoding="utf-8")
IOS_BRIEF = (SAMPLES / "cisco_ios" / "show_ip_interface_brief.txt").read_text(encoding="utf-8")


def _dev(conn, name):
    return conn.execute("SELECT * FROM devices WHERE name = ?", (name,)).fetchone()


def _ifaces(conn, name):
    return {r["name"]: r for r in conn.execute(
        "SELECT i.* FROM interfaces i JOIN devices d ON d.id = i.device_id WHERE d.name = ?", (name,))}


def _sync(client, conn, name, **body):
    return client.post(f"/api/devices/{_dev(conn, name)['id']}/interfaces/sync", json=body)


# ---------------------------------------------------------------------------
# 1. Lectura de la salida de cada fabricante
# ---------------------------------------------------------------------------
def test_lee_router_c8200():
    rows = {r["name"]: r for r in parse_interfaces("cisco_xe", XE_BRIEF)}
    assert len(rows) == 4
    assert rows["GigabitEthernet0/0/0"] == {"name": "GigabitEthernet0/0/0", "ip": "192.168.100.1", "status": "up"}
    assert rows["GigabitEthernet0/0/1"]["status"] == "admin_down" and rows["GigabitEthernet0/0/1"]["ip"] is None


def test_lee_switch_2960_completo():
    rows = {r["name"]: r for r in parse_interfaces("cisco_ios", IOS_BRIEF)}
    assert len(rows) == 27                                    # Vlan1 + 24 Fa + 2 Gi
    assert rows["Vlan1"]["ip"] == "192.168.100.2" and rows["FastEthernet0/1"]["status"] == "up"
    assert rows["FastEthernet0/24"]["status"] == "down"


def test_up_con_protocolo_down_es_down():
    text = "GigabitEthernet0/0/2   unassigned      YES unset  up                    down"
    assert parse_interfaces("cisco_xe", text)[0]["status"] == "down"


def test_lee_huawei_y_fortinet():
    hw = parse_interfaces("huawei", "Interface                 IP Address/Mask    Physical  Protocol\n"
                                    "GigabitEthernet0/0/0      192.0.2.1/24       up        up\n"
                                    "GigabitEthernet0/0/1      unassigned         *down     down\n"
                                    "Vlanif10                  198.51.100.1/24    up        up(s)")
    assert [(r["name"], r["status"]) for r in hw] == [("GigabitEthernet0/0/0", "up"),
                                                     ("GigabitEthernet0/0/1", "admin_down"), ("Vlanif10", "up")]
    assert hw[0]["ip"] == "192.0.2.1"
    fg = parse_interfaces("fortinet", "    ==[wan1]  mode: static  ip: 198.51.100.1 255.255.255.0  status: up\n"
                                      "    ==[port3]  mode: static  ip: 0.0.0.0 0.0.0.0  status: down")
    assert fg == [{"name": "wan1", "ip": "198.51.100.1", "status": "up"},
                  {"name": "port3", "ip": None, "status": "down"}]


def test_lineas_que_no_son_interfaces_se_ignoran():
    text = "Interface   IP-Address  OK? Method Status   Protocol\n\n% Invalid input detected\nRouter#"
    assert parse_interfaces("cisco_ios", text) == []


# ---------------------------------------------------------------------------
# 2. Sincronización con el inventario
# ---------------------------------------------------------------------------
def test_primera_lectura_registra_todo(client, conn):
    r = _sync(client, conn, "SIM-CORE-RTR01")
    assert r.status_code == 200 and len(r.json["summary"]["nuevas"]) == 4
    assert r.json["serial_number"] == "FGL2601SIM1"
    gi0 = _ifaces(conn, "SIM-CORE-RTR01")["GigabitEthernet0/0/0"]
    assert gi0["source"] == "equipo" and gi0["ip_address"] == "192.168.100.1" and gi0["last_seen_at"]


def test_segunda_lectura_sin_cambios(client, conn):
    _sync(client, conn, "SIM-CORE-RTR01")
    s = _sync(client, conn, "SIM-CORE-RTR01").json["summary"]
    assert s["nuevas"] == [] and len(s["sin_cambios"]) == 4


def test_cambio_de_estado_se_detecta(client, conn):
    _sync(client, conn, "SIM-CORE-RTR01")
    conn.execute("UPDATE interfaces SET status = 'down' WHERE name = 'GigabitEthernet0/0/0'")
    conn.commit()
    s = _sync(client, conn, "SIM-CORE-RTR01").json["summary"]
    assert s["actualizadas"] == ["GigabitEthernet0/0/0: down -> up"]


def test_desaparecidas_se_reportan_y_solo_se_borran_si_se_pide(client, conn):
    dev = _dev(conn, "SIM-CORE-RTR01")
    client.post(f"/api/devices/{dev['id']}/interfaces", json={"name": "GigabitEthernet0/0/9"})   # registro viejo
    s = _sync(client, conn, "SIM-CORE-RTR01").json["summary"]
    assert s["desaparecidas"] == ["GigabitEthernet0/0/9"] and s["eliminadas"] == []
    assert "GigabitEthernet0/0/9" in _ifaces(conn, "SIM-CORE-RTR01")
    s = _sync(client, conn, "SIM-CORE-RTR01", remove_missing=True).json["summary"]
    assert s["eliminadas"] == ["GigabitEthernet0/0/9"]
    assert "GigabitEthernet0/0/9" not in _ifaces(conn, "SIM-CORE-RTR01")


def test_respeta_la_descripcion_manual(client, conn):
    dev = _dev(conn, "SIM-CORE-RTR01")
    client.post(f"/api/devices/{dev['id']}/interfaces",
                json={"name": "Gi0/0/0", "description": "Enlace al switch", "status": "down"})
    _sync(client, conn, "SIM-CORE-RTR01")
    gi0 = _ifaces(conn, "SIM-CORE-RTR01")["GigabitEthernet0/0/0"]
    assert gi0["description"] == "Enlace al switch" and gi0["status"] == "up"


def test_nombres_invalidos_de_la_salida_se_rechazan(conn):
    # La salida del equipo también es un dato NO confiable
    rows = [{"name": "GigabitEthernet0/0/0", "ip": None, "status": "up"},
            {"name": "port1;reload", "ip": None, "status": "up"},
            {"name": "wan1", "ip": None, "status": "up"}]          # nombre de FortiGate en un Cisco
    s = apply_sync(conn, _dev(conn, "SIM-CORE-RTR01"), rows, "tester")
    assert s["nuevas"] == ["GigabitEthernet0/0/0"] and len(s["invalidas"]) == 2
    row = conn.execute("SELECT result FROM audit_log WHERE action = 'interface.sync'").fetchone()
    assert row["result"] == "alerta"


def test_queda_auditado_con_el_usuario(role_client, conn):
    c = role_client("operador", "erick")
    _sync(c, conn, "SIM-DIST-SW01")
    row = conn.execute("SELECT actor, detail FROM audit_log WHERE action = 'interface.sync'").fetchone()
    assert row["actor"] == "erick" and "nuevas=27" in row["detail"]


# ---------------------------------------------------------------------------
# 3. Integración: con las interfaces reales, la marca interfaz_desconocida funciona sola
# ---------------------------------------------------------------------------
def test_despues_de_leer_el_equipo_se_detecta_una_interfaz_inexistente(client, conn):
    _sync(client, conn, "SIM-CORE-RTR01")
    raw = ("<187>1: *Oct  5 10:15:42.551: SIM-CORE-RTR01 %LINK-3-UPDOWN: "
           "Interface GigabitEthernet0/0/{n}, changed state to down")
    ok = ingest(conn, raw.format(n=2), "192.0.2.1", "simulador")
    bad = ingest(conn, raw.format(n=9), "192.0.2.1", "simulador")
    assert "interfaz_desconocida" not in ok["flags"] and "interfaz_desconocida" in bad["flags"]


# ---------------------------------------------------------------------------
# 4. Errores y permisos
# ---------------------------------------------------------------------------
def test_equipo_sin_conexion(client, conn):
    r = _sync(client, conn, "SIM-EDGE-FW01")              # fortinet sin plataforma ni modo
    assert r.status_code == 400


def test_falla_de_conexion_no_toca_el_inventario(client, conn, monkeypatch):
    class Falla:
        transport, target, host_key_fp = "consola", "COM3", None

        def open(self):
            raise connector.ConnectionError_("No se pudo conectar (consola COM3): el puerto COM3 no existe")

        def close(self):
            pass
    monkeypatch.setattr(connector, "make_transport", lambda device, conn: Falla())
    r = _sync(client, conn, "SIM-CORE-RTR01")
    assert r.status_code == 502 and _ifaces(conn, "SIM-CORE-RTR01") == {}


def test_salida_irreconocible(client, conn, monkeypatch):
    class Raro(connector.SimulatedTransport):
        def send(self, command):
            return "salida inesperada" if "interface" in command else super().send(command)
    monkeypatch.setattr(connector, "make_transport", lambda device, conn: Raro(device, conn))
    r = _sync(client, conn, "SIM-CORE-RTR01")
    assert r.status_code == 502 and "no se reconoció" in r.json["errors"][0]


def test_auditor_no_sincroniza(role_client, conn):
    c = role_client("auditor")
    assert _sync(c, conn, "SIM-CORE-RTR01").status_code == 403


def test_migracion_agrega_columnas(conn):
    from app.db import init_db
    for col in ("ip_address", "source", "last_seen_at"):
        conn.execute(f"ALTER TABLE interfaces DROP COLUMN {col}")
    conn.commit()
    init_db(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(interfaces)")}
    assert {"ip_address", "source", "last_seen_at"} <= cols


@pytest.mark.parametrize("platform", ["cisco_ios", "cisco_xe"])
def test_el_comando_esta_en_la_lista_permitida(platform):
    from app.console import check
    from app.interfaces import SYNC_COMMAND
    assert check("Cisco", SYNC_COMMAND[platform], "tester")[0]
