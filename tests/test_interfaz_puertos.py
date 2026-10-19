"""
Pruebas de la Fase 7 (paso 7.1): interfaz y puertos en los eventos, y
tiempos de respuesta de los incidentes (base de MTTA/MTTR).

Todos los mensajes usan IP de documentación (RFC 5737): son DATOS SIMULADOS.
"""
import pytest

from app.db import init_db
from app.ingest import ingest
from app.syslog_parser import is_valid_interface, is_valid_port, normalize_interface, parse


# ---------------------------------------------------------------------------
# 1. Parser: interfaz por fabricante
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw, interface", [
    # Cisco, nombre largo
    ("<187>1: *Oct  5 10:15:42.551: R1 %LINK-3-UPDOWN: Interface GigabitEthernet0/0/2, changed state to down",
     "GigabitEthernet0/0/2"),
    # Cisco, nombre corto -> se guarda el nombre largo
    ("<187>2: *Oct  5 10:15:42.551: R1 %LINK-3-UPDOWN: Interface Gi0/1, changed state to down",
     "GigabitEthernet0/1"),
    # Cisco, subinterfaz
    ("<189>3: *Oct  5 10:15:42.551: R1 %LINEPROTO-5-UPDOWN: Line protocol on Interface "
     "GigabitEthernet0/0/1.100, changed state to up", "GigabitEthernet0/0/1.100"),
    # Huawei VRP
    ("<186>Oct 5 2026 13:05:10 R2 %%01IFNET/2/LINK_STATE(l)[1]: The interface GigabitEthernet0/0/1 changed to DOWN.",
     "GigabitEthernet0/0/1"),
    # Huawei, interfaz VLAN
    ("<188>Oct 5 2026 13:05:10 SW1 %%01IFNET/4/IF_STATE(l)[2]: Interface Vlanif10 has turned into DOWN state.",
     "Vlanif10"),
    # Fortinet, clave=valor
    ('<188>date=2026-10-05 time=23:52:10 devname="FW1" logid="0000000013" type="traffic" '
     'level="warning" srcport=51520 srcintf="wan1" dstport=3389 dstintf="internal"', "wan1"),
    # Fortinet, texto libre en msg
    ('<188>date=2026-10-05 time=12:44:01 devname="FW1" logid="0100022921" type="event" '
     'level="warning" msg="Interface port3 bandwidth usage above 85%"', "port3"),
])
def test_extrae_interfaz(raw, interface):
    assert parse(raw)["interface"] == interface


def test_mensaje_sin_interfaz():
    p = parse("<189>4: *Oct  5 14:02:33.123: R1 %SYS-5-CONFIG_I: Configured from console by noc_admin")
    assert p["interface"] is None and p["src_port"] is None and p["dst_port"] is None


def test_comando_display_interface_no_es_una_interfaz():
    # "display interface brief" es un COMANDO registrado, no una interfaz afectada
    p = parse('<189>Oct 5 2026 09:12:45 R2 %%01SHELL/5/CMDRECORD(s)[0]: Recorded command information. '
              '(Task=VT0, Ip=192.0.2.50, User=noc_admin, Command="display interface brief")')
    assert p["interface"] is None


# ---------------------------------------------------------------------------
# 2. Parser: puertos (origen y destino del ataque)
# ---------------------------------------------------------------------------
def test_puertos_acl_cisco():
    p = parse("<190>5: *Oct  5 23:47:30.000: R1 %SEC-6-IPACCESSLOGP: list 101 denied tcp "
              "203.0.113.200(51515) -> 192.0.2.1(23), 1 packet")
    assert (p["src_port"], p["dst_port"]) == (51515, 23)


def test_puerto_atacado_en_login_cisco():
    p = parse("<188>6: *Oct  5 23:47:10.001: R1 %SEC_LOGIN-4-LOGIN_FAILED: Login failed [user: root] "
              "[Source: 203.0.113.200] [localport: 22] [Reason: Login Authentication Failed]")
    assert p["dst_port"] == 22 and p["src_port"] is None


def test_puertos_fortinet():
    p = parse('<188>date=2026-10-05 time=23:52:10 devname="FW1" logid="0000000013" type="traffic" '
              'level="warning" srcip=203.0.113.200 srcport=51520 srcintf="wan1" dstport=3389')
    assert (p["src_port"], p["dst_port"]) == (51520, 3389)


def test_puerto_de_origen_estilo_sshd():
    p = parse("<38>Oct  5 23:00:00 srv sshd[812]: Failed password for root from 203.0.113.200 port 40022 ssh2")
    assert p["src_port"] == 40022


def test_puerto_del_servidor_syslog_no_se_confunde():
    # "Logging to host X port 5514" es la configuración del NOC, no un ataque
    p = parse("<190>7: *Oct  5 08:00:05.300: R1 %SYS-6-LOGGINGHOST_STARTSTOP: "
              "Logging to host 192.0.2.250 port 5514 started - CLI initiated")
    assert p["src_port"] is None and p["dst_port"] is None


def test_puerto_fuera_de_rango_se_marca_y_no_se_guarda():
    p = parse("<190>8: *Oct  5 23:47:30.000: R1 %SEC-6-IPACCESSLOGP: list 101 denied tcp "
              "203.0.113.200(70000) -> 192.0.2.1(0), 1 packet")
    assert p["src_port"] is None and p["dst_port"] is None
    assert "puerto_invalido" in p["parse_flags"]


# ---------------------------------------------------------------------------
# 3. Funciones de validación
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value, ok", [(1, True), ("22", True), (65535, True),
                                       (0, False), (65536, False), ("abc", False), (None, False)])
def test_validar_puerto(value, ok):
    assert is_valid_port(value) is ok


@pytest.mark.parametrize("name, ok", [("Gi0/1", True), ("GigabitEthernet0/0/1.100", True),
                                      ("port1", True), ("Eth-Trunk1", True),
                                      ("1Gi", False), ("Gi0/1; reload", False), ("", False),
                                      ("<script>", False)])
def test_validar_sintaxis_de_interfaz(name, ok):
    assert is_valid_interface(name) is ok


def test_normalizar_interfaz():
    assert normalize_interface("Gi0/1") == "GigabitEthernet0/1"
    assert normalize_interface("Te1/0/1") == "TenGigabitEthernet1/0/1"
    assert normalize_interface("port1") == "port1"        # FortiGate: se deja igual


# ---------------------------------------------------------------------------
# 4. Ingesta y API de eventos
# ---------------------------------------------------------------------------
def test_ingesta_guarda_interfaz_y_puertos(conn):
    r = ingest(conn, "<190>9: *Oct  5 23:47:30.000: SIM-CORE-RTR01 %SEC-6-IPACCESSLOGP: list 101 "
                     "denied tcp 203.0.113.200(51515) -> 192.0.2.1(23), 1 packet", "192.0.2.1", "simulador")
    row = conn.execute("SELECT interface, src_port, dst_port FROM syslog_events WHERE id = ?",
                       (r["id"],)).fetchone()
    assert (row["src_port"], row["dst_port"]) == (51515, 23)


def test_filtrar_por_interfaz_y_puerto(client, conn):
    ingest(conn, "<187>10: *Oct  5 10:15:42.551: SIM-CORE-RTR01 %LINK-3-UPDOWN: "
                 "Interface GigabitEthernet0/0/2, changed state to down", "192.0.2.1", "simulador")
    ingest(conn, "<188>11: *Oct  5 23:47:10.001: SIM-CORE-RTR01 %SEC_LOGIN-4-LOGIN_FAILED: "
                 "Login failed [user: root] [Source: 203.0.113.200] [localport: 22]", "192.0.2.1", "simulador")
    # El nombre corto encuentra el evento guardado con el nombre largo
    r = client.get("/api/events?interface=Gi0/0/2")
    assert r.status_code == 200 and len(r.json) == 1 and r.json[0]["interface"] == "GigabitEthernet0/0/2"
    r = client.get("/api/events?port=22")
    assert len(r.json) == 1 and r.json[0]["dst_port"] == 22


def test_filtros_de_interfaz_y_puerto_invalidos_dan_400(client):
    r = client.get("/api/events?port=70000&interface=Gi0/1;reload")
    assert r.status_code == 400
    text = " ".join(r.json["errors"])
    assert "Puerto inválido" in text and "Interfaz inválida" in text


# ---------------------------------------------------------------------------
# 5. Tiempos de respuesta de incidentes (MTTA / MTTR)
# ---------------------------------------------------------------------------
def test_tiempos_de_respuesta_se_registran_una_sola_vez(client):
    inc = client.post("/api/incidents", json={"title": "Prueba de tiempos", "severity": 3}).json
    url = f"/api/incidents/{inc['id']}"
    assert inc["assigned_at"] is None and inc["started_at"] is None

    first = client.post(f"{url}/assign", json={"assigned_to": "Erick"}).json
    assert first["assigned_at"]
    # Reasignar NO cambia la primera fecha de asignación
    again = client.post(f"{url}/assign", json={"assigned_to": "Otro operador"}).json
    assert again["assigned_at"] == first["assigned_at"]

    started = client.post(f"{url}/status", json={"status": "en_progreso"}).json
    assert started["started_at"]
    closed = client.post(f"{url}/status", json={"status": "cerrado",
                                                "resolution": "Se reemplazó el patch cord"}).json
    assert closed["started_at"] == started["started_at"] and closed["closed_at"]
    assert closed["created_at"] <= closed["assigned_at"] <= closed["started_at"] <= closed["closed_at"]


# ---------------------------------------------------------------------------
# 6. Migración: una base del Corte 2 recibe las columnas nuevas sin perder datos
# ---------------------------------------------------------------------------
def test_migracion_agrega_columnas_sin_borrar_datos(conn):
    ingest(conn, "<187>12: *Oct  5 10:15:42.551: SIM-CORE-RTR01 %LINK-3-UPDOWN: "
                 "Interface Gi0/1, changed state to down", "192.0.2.1", "simulador")
    before = conn.execute("SELECT COUNT(*) FROM syslog_events").fetchone()[0]
    # Simula una base v0.2.0: se quitan las columnas de la Fase 7 (y antes el
    # índice de la Fase 7.4 sobre 'interface', que en v0.2.0 tampoco existía)
    conn.execute("DROP INDEX IF EXISTS idx_events_interface")
    for table, col in [("syslog_events", "interface"), ("syslog_events", "src_port"),
                       ("syslog_events", "dst_port"), ("incidents", "assigned_at"),
                       ("incidents", "started_at")]:
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
    conn.commit()

    init_db(conn)   # lo que ocurre al arrancar la aplicación

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(syslog_events)")}
    assert {"interface", "src_port", "dst_port"} <= cols
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(incidents)")}
    assert {"assigned_at", "started_at"} <= cols
    assert conn.execute("SELECT COUNT(*) FROM syslog_events").fetchone()[0] == before
    # Y el índice se crea después de migrar (Fase 7.4)
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'idx_events_interface'").fetchone()
