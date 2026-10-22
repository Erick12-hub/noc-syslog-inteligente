"""
Pruebas de la Fase 9.4: diagnóstico desde el equipo (ping y traceroute).

En modo simulado responde la red del laboratorio (192.168.100.0/24) y las de
documentación; el resto "no responde". Las salidas reales de Huawei y Fortinet
se prueban con textos de ejemplo.
"""
import pytest

from app.config import Config
from app.connector import run_session
from app.diagnostics import LIMITER, parse_ping, parse_traceroute, validate_target


@pytest.fixture(autouse=True)
def reset_limiter():
    LIMITER.reset()
    yield
    LIMITER.reset()


def _dev(conn, name="SIM-CORE-RTR01"):
    return conn.execute("SELECT * FROM devices WHERE name = ?", (name,)).fetchone()


def _diag(client, conn, kind, target, name="SIM-CORE-RTR01"):
    return client.post(f"/api/devices/{_dev(conn, name)['id']}/diagnostic", json={"type": kind, "target": target})


# ---------------------------------------------------------------------------
# 1. Validación del destino
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("target", ["192.168.100.10", "10.20.30.1", "172.16.0.1", "192.0.2.1"])
def test_destinos_permitidos(target):
    assert validate_target(target) == (target, [])


@pytest.mark.parametrize("target, message", [
    ("8.8.8.8", "fuera de las redes permitidas"),          # Internet
    ("224.0.0.1", "no es una dirección de un solo equipo"),  # multicast
    ("0.0.0.0", "no es una dirección de un solo equipo"),
    ("255.255.255.255", "no es una dirección de un solo equipo"),
    ("192.168.100.300", "IPv4"),
    ("192.168.100.10; reload", "IPv4"),                     # intento de inyección
    ("", "IPv4"),
])
def test_destinos_rechazados(target, message):
    ip, errors = validate_target(target)
    assert ip is None and message in errors[0]


# ---------------------------------------------------------------------------
# 2. Lectura de resultados
# ---------------------------------------------------------------------------
def test_ping_cisco():
    r = parse_ping("!!!!!\nSuccess rate is 100 percent (5/5), round-trip min/avg/max = 1/2/4 ms")
    assert r == {"recognized": True, "sent": 5, "received": 5, "success_pct": 100, "avg_ms": 2, "reachable": True}
    r = parse_ping(".....\nSuccess rate is 0 percent (0/5)")
    assert r["reachable"] is False and r["avg_ms"] is None


def test_ping_parcial():
    r = parse_ping(".!!!!\nSuccess rate is 80 percent (4/5), round-trip min/avg/max = 1/1/1 ms")
    assert r["success_pct"] == 80 and r["reachable"]


def test_ping_huawei_y_fortinet():
    hw = parse_ping("  --- 192.0.2.10 ping statistics ---\n    5 packet(s) transmitted\n    5 packet(s) received\n"
                    "    0.00% packet loss\n    round-trip min/avg/max = 1/2/3 ms")
    fg = parse_ping("--- 192.0.2.10 ping statistics ---\n5 packets transmitted, 4 packets received, 20% packet loss\n"
                    "round-trip min/avg/max = 0.4/0.6/0.9 ms")
    assert fg["success_pct"] == 80 and fg["avg_ms"] == 0.6
    assert hw["received"] == 5 and hw["success_pct"] == 100 and hw["avg_ms"] == 2.0   # Huawei: varias líneas


def test_traceroute_cisco():
    text = ("Type escape sequence to abort.\nTracing the route to 10.0.0.9\n"
            "  1 192.168.100.1 1 msec 0 msec 1 msec\n  2 10.0.0.1 4 msec 5 msec 3 msec\n"
            "  3 10.0.0.9 8 msec 9 msec 7 msec")
    r = parse_traceroute(text, "10.0.0.9")
    assert [h["ip"] for h in r["hops"]] == ["192.168.100.1", "10.0.0.1", "10.0.0.9"]
    assert r["hops"][1]["avg_ms"] == 4.0 and r["reached"]


def test_traceroute_con_saltos_sin_respuesta():
    r = parse_traceroute("  1 192.168.100.1 1 msec 1 msec 0 msec\n  2  *  *  *\n  3  *  *  *", "10.9.9.9")
    assert r["hops"][1] == {"hop": 2, "ip": None, "avg_ms": None} and r["reached"] is False


def test_salida_irreconocible():
    assert parse_ping("% Unrecognized host or address")["recognized"] is False
    assert parse_traceroute("% Invalid input detected", "10.0.0.1")["recognized"] is False


# ---------------------------------------------------------------------------
# 3. API (modo simulado)
# ---------------------------------------------------------------------------
def test_ping_al_pc_del_noc(role_client, conn):
    c = role_client("operador", "erick")
    r = _diag(c, conn, "ping", "192.168.100.10")
    assert r.status_code == 200
    assert r.json["command"] == "ping 192.168.100.10" and r.json["result"]["success_pct"] == 100
    assert r.json["summary"] == "ping 192.168.100.10: 100% (5/5), promedio 1 ms"
    assert r.json["serial_number"] == "FGL2601SIM1"
    row = conn.execute("SELECT actor, detail, result FROM audit_log WHERE action = 'device.diagnostic'").fetchone()
    assert row["actor"] == "erick" and "100%" in row["detail"] and row["result"] == "ok"


def test_destino_sin_respuesta_queda_como_alerta(client, conn):
    r = _diag(client, conn, "ping", "10.9.9.9")
    assert r.json["result"]["reachable"] is False
    assert conn.execute("SELECT result FROM audit_log WHERE action = 'device.diagnostic'").fetchone()["result"] == "alerta"


def test_traceroute(client, conn):
    r = _diag(client, conn, "traceroute", "10.9.9.9")
    assert r.status_code == 200 and len(r.json["result"]["hops"]) == 3 and not r.json["result"]["reached"]
    r = _diag(client, conn, "traceroute", "192.168.100.10")
    assert r.json["result"]["reached"]


def test_switch_usa_el_mismo_comando(client, conn):
    r = _diag(client, conn, "ping", "192.168.100.1", "SIM-DIST-SW01")
    assert r.status_code == 200 and r.json["serial_number"] == "FOC1234SIM3"


def test_internet_bloqueado_sin_conectarse(client, conn):
    r = _diag(client, conn, "ping", "8.8.8.8")
    assert r.status_code == 400
    assert conn.execute("SELECT COUNT(*) FROM device_sessions").fetchone()[0] == 0


def test_tipo_invalido(client, conn):
    r = _diag(client, conn, "nmap", "192.168.100.10")
    assert r.status_code == 400 and "Tipo inválido" in r.json["errors"][0]


def test_limite_por_minuto(client, conn, monkeypatch):
    monkeypatch.setattr(Config, "DIAG_MAX_PER_MINUTE", 2)
    assert _diag(client, conn, "ping", "192.168.100.10").status_code == 200
    assert _diag(client, conn, "ping", "192.168.100.10").status_code == 200
    r = _diag(client, conn, "ping", "192.168.100.10")
    assert r.status_code == 429 and "Límite" in r.json["errors"][0]
    row = conn.execute("SELECT result FROM audit_log WHERE action = 'device.diagnostic_limit'").fetchone()
    assert row["result"] == "bloqueado"


def test_ping_por_la_sesion_normal_se_bloquea(conn):
    # Sin pasar por Diagnóstico no hay validación de destino: se bloquea
    result, status = run_session(conn, _dev(conn), ["ping 192.168.100.10"], "tester")
    assert status == 403 and "Diagnóstico" in result["errors"][1]


def test_auditor_no_ejecuta_diagnosticos(role_client, conn):
    assert _diag(role_client("auditor"), conn, "ping", "192.168.100.10").status_code == 403


def test_equipo_sin_conexion(client, conn):
    assert _diag(client, conn, "ping", "192.168.100.10", "SIM-EDGE-FW01").status_code == 400
