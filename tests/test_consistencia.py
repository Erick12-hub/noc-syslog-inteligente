"""
Pruebas de la Fase 9.5: reloj (NTP), consistencia, cadena de auditoría automática
y correcciones del generador con los hallazgos del laboratorio (21-oct-2026).

Los casos de reloj reproducen la sesión real: el router quedó 5 h atrás (se puso
la hora antes que la zona) y el switch 2960 arrancó con el reloj en 1993.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.configgen import _validate_baseline, baseline
from app.consistency import CHAIN_KEY, clock_status, human, run_checks, run_consistency
from app.db import now_iso

NOW = datetime(2026, 10, 21, 19, 30, tzinfo=timezone.utc)
ISO = "%Y-%m-%dT%H:%M:%SZ"


def _dev(conn, name):
    return conn.execute("SELECT * FROM devices WHERE name = ?", (name,)).fetchone()


def _event(conn, device, received: datetime, event_time: datetime | None, flags=None):
    """Inserta un evento con horas controladas (recibido y del equipo)."""
    conn.execute(
        "INSERT INTO syslog_events (received_at, source_ip, device_id, vendor, severity, message, raw, origin, "
        "authorized_source, flags, event_time_utc) VALUES (?, ?, ?, 'Cisco', 6, 'prueba', 'prueba', 'udp', 1, ?, ?)",
        (received.strftime(ISO), device["ip"], device["id"], flags,
         event_time.strftime(ISO) if event_time else None))
    conn.commit()


def _lab(conn):
    """Los dos equipos REALES de la sesión 1 (no simulados)."""
    ts = now_iso()
    for name, ip, platform in (("LAB-RTR01", "192.168.100.1", "cisco_xe"), ("LAB-SW01", "192.168.100.2", "cisco_ios")):
        conn.execute("INSERT INTO devices (name, ip, vendor, status, authorized, is_simulated, created_at, "
                     "updated_at, connection_mode, platform, console_port) VALUES (?, ?, 'Cisco', 'activo', 1, 0, "
                     "?, ?, 'consola', ?, 'COM5')", (name, ip, ts, ts, platform))
    conn.commit()
    return _dev(conn, "LAB-RTR01"), _dev(conn, "LAB-SW01")


def _checks(findings, check):
    return [f for f in findings if f["check"] == check]


# ---------------------------------------------------------------------------
# 1. Reloj (NTP)
# ---------------------------------------------------------------------------
def test_router_5_horas_atrasado(conn):
    rtr, _ = _lab(conn)
    _event(conn, rtr, NOW, NOW - timedelta(hours=5))
    c = clock_status(conn, rtr["id"])
    assert c["status"] == "critico" and c["offset_s"] == 18000 and c["text"] == "Reloj atrasado 5 h 0 min"


def test_switch_con_reloj_de_1993(conn):
    _, sw = _lab(conn)
    _event(conn, sw, NOW, datetime(1993, 3, 1, 0, 3, 40, tzinfo=timezone.utc))
    c = clock_status(conn, sw["id"])
    assert c["status"] == "critico" and "34 años" in c["text"]
    f = _checks(run_checks(conn, NOW)["findings"], "reloj_desfasado")[0]
    assert "reloj de fábrica" in f["suggestion"]


@pytest.mark.parametrize("seconds, status, word", [(0.5, "ok", "Sincronizado"), (1, "ok", "Sincronizado"),
                                                    (10, "aviso", "atrasado"), (-10, "aviso", "adelantado"),
                                                    (120, "critico", "atrasado")])
def test_umbrales(conn, seconds, status, word):
    rtr, _ = _lab(conn)
    _event(conn, rtr, NOW, NOW - timedelta(seconds=seconds))
    c = clock_status(conn, rtr["id"])
    assert c["status"] == status and word in c["text"]


def test_la_mediana_ignora_un_evento_aislado(conn):
    rtr, _ = _lab(conn)
    for i in range(4):
        _event(conn, rtr, NOW + timedelta(seconds=i), NOW + timedelta(seconds=i))     # sincronizado
    _event(conn, rtr, NOW + timedelta(seconds=9), NOW - timedelta(hours=5))           # uno raro
    assert clock_status(conn, rtr["id"])["status"] == "ok"


def test_sin_eventos_con_fecha(conn):
    rtr, _ = _lab(conn)
    _event(conn, rtr, NOW, None)
    assert clock_status(conn, rtr["id"])["status"] == "sin_datos"


@pytest.mark.parametrize("seconds, text", [(3.2, "3 s"), (90, "1 min 30 s"), (18000, "5 h 0 min"),
                                           (86400 * 10, "10 días"), (1.07e9, "34 años")])
def test_texto_legible(seconds, text):
    assert human(seconds) == text


# ---------------------------------------------------------------------------
# 2. Chequeos de consistencia
# ---------------------------------------------------------------------------
def test_equipo_real_que_nunca_envio_eventos(conn):
    _lab(conn)
    found = _checks(run_checks(conn, NOW)["findings"], "sin_eventos")
    assert {f["device"] for f in found} == {"LAB-RTR01", "LAB-SW01"} and found[0]["severity"] == "info"
    # Los equipos SIM sin eventos no generan ruido
    assert not any(f["device"].startswith("SIM-") for f in found)


def test_equipo_callado(conn):
    rtr, _ = _lab(conn)
    _event(conn, rtr, NOW - timedelta(hours=30), NOW - timedelta(hours=30))
    f = [x for x in _checks(run_checks(conn, NOW)["findings"], "sin_eventos") if x["device"] == "LAB-RTR01"][0]
    assert f["severity"] == "aviso" and "más de 24 h" in f["detail"]


def test_interfaz_desconocida_y_marca_inconsistente(conn):
    rtr, _ = _lab(conn)
    _event(conn, rtr, NOW - timedelta(hours=1), NOW - timedelta(hours=1), "interfaz_desconocida")
    _event(conn, rtr, NOW - timedelta(hours=2), NOW - timedelta(hours=2), "marca_inconsistente,fecha_futura")
    found = run_checks(conn, NOW)["findings"]
    assert "1 eventos de interfaces no registradas" in _checks(found, "interfaz_desconocida")[0]["detail"]
    assert _checks(found, "marca_inconsistente")[0]["severity"] == "aviso"


def test_ip_del_inventario_que_el_equipo_no_tiene(client, conn):
    # SIM-CORE-RTR01 está en el inventario con 192.0.2.1, pero el equipo reporta 192.168.100.1
    client.post(f"/api/devices/{_dev(conn, 'SIM-CORE-RTR01')['id']}/interfaces/sync", json={})
    f = _checks(run_checks(conn, NOW)["findings"], "ip_inventario")[0]
    assert f["device"] == "SIM-CORE-RTR01" and "192.0.2.1" in f["detail"] and "192.168.100.1" in f["detail"]


def test_ip_duplicada_entre_equipos(client, conn):
    rtr, _ = _lab(conn)
    # El router simulado reporta 192.168.100.1, la misma IP del router real del laboratorio
    client.post(f"/api/devices/{_dev(conn, 'SIM-CORE-RTR01')['id']}/interfaces/sync", json={})
    f = _checks(run_checks(conn, NOW)["findings"], "ip_duplicada")[0]
    assert f["severity"] == "critico" and "192.168.100.1" in f["detail"]
    assert "LAB-RTR01" in f["device"] and "SIM-CORE-RTR01" in f["device"]


def test_orden_por_gravedad(conn):
    rtr, sw = _lab(conn)
    _event(conn, rtr, NOW, NOW - timedelta(hours=5))              # crítico
    _event(conn, sw, NOW - timedelta(hours=30), NOW - timedelta(hours=30))   # aviso
    sev = [f["severity"] for f in run_checks(conn, NOW)["findings"]]
    assert sev == sorted(sev, key=["critico", "aviso", "info"].index)


# ---------------------------------------------------------------------------
# 3. Cadena de auditoría: verificación automática con incidente de severidad 1
# ---------------------------------------------------------------------------
def _break_chain(conn):
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    conn.execute("UPDATE audit_log SET actor = 'alterado' WHERE id = (SELECT MIN(id) FROM audit_log)")
    conn.commit()


def test_cadena_rota_abre_un_solo_incidente(conn):
    _break_chain(conn)
    r = run_consistency(conn, "sistema", NOW)
    assert r["chain"]["ok"] is False and r["incident"]
    inc = conn.execute("SELECT severity, title, correlation_key FROM incidents WHERE id = ?", (r["incident"],)).fetchone()
    assert inc["severity"] == 1 and "cadena rota" in inc["title"] and inc["correlation_key"] == CHAIN_KEY
    again = run_consistency(conn, "sistema", NOW)
    assert again["incident"] == r["incident"]                     # no se duplica mientras siga abierto
    assert conn.execute("SELECT COUNT(*) FROM incidents WHERE correlation_key = ?", (CHAIN_KEY,)).fetchone()[0] == 1


def test_cadena_integra_no_abre_incidentes(conn):
    r = run_consistency(conn, "sistema", NOW)
    assert r["chain"]["ok"] and r["incident"] is None
    row = conn.execute("SELECT result FROM audit_log WHERE action = 'consistency.run'").fetchone()
    assert row["result"] == "ok"


def test_el_receptor_revisa_y_no_se_cae(conn, capsys, monkeypatch):
    from app import receiver
    _break_chain(conn)
    receiver._periodic_check(conn)
    assert "cadena de auditoría ROTA" in capsys.readouterr().out
    monkeypatch.setattr("app.consistency.run_consistency", lambda c, u: 1 / 0)
    receiver._periodic_check(conn)                               # un error no detiene la recepción
    assert "no se pudo revisar" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 4. API y permisos
# ---------------------------------------------------------------------------
def test_consulta_sin_efectos(role_client, conn):
    before = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    r = role_client("auditor").get("/api/consistency")
    assert r.status_code == 200 and "findings" in r.json and "clocks" in r.json
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'consistency.run'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] >= before


def test_revisar_ahora_requiere_operador(role_client, conn):
    assert role_client("auditor").post("/api/consistency/run").status_code == 403
    r = role_client("operador", "erick").post("/api/consistency/run")
    assert r.status_code == 200
    assert conn.execute("SELECT actor FROM audit_log WHERE action = 'consistency.run'").fetchone()["actor"] == "erick"


def test_dashboard_muestra_el_panel(role_client):
    html = role_client("operador").get("/").get_data(as_text=True)
    assert 'id="consistency"' in html and 'data-can-run="1"' in html
    assert 'data-can-run="0"' in role_client("auditor").get("/").get_data(as_text=True)


# ---------------------------------------------------------------------------
# 5. Generador corregido con los hallazgos del laboratorio
# ---------------------------------------------------------------------------
ROUTER = {"role": "router", "mode": "prestamo", "hostname": "LAB-RTR01", "mgmt_ip": "192.168.100.1",
          "prefix": "24", "noc_ip": "192.168.100.10", "port": "5514", "severity": "6"}
SWITCH = {**ROUTER, "role": "switch", "hostname": "LAB-SW01", "mgmt_ip": "192.168.100.2", "gateway": "192.168.100.1"}


def _blocks(args):
    return baseline(_validate_baseline(args)[0])


@pytest.mark.parametrize("args", [ROUTER, SWITCH, {**SWITCH, "mgmt_if": "vlan10"}], ids=["router", "switch", "vlan10"])
def test_trozos_cortos_e_independientes(args):
    chunks = next(b for b in _blocks(args) if b["kind"] == "pegar")["chunks"]
    assert len(chunks) >= 8
    for c in chunks:
        lines = c["text"].splitlines()
        assert lines[0] == "configure terminal" and lines[-1] == "end"
        assert len(lines) - 2 <= 5                                  # 5 comandos o menos por trozo
        assert not any(line.startswith("!") for line in lines)      # sin comentarios: menos texto por consola


def test_router_primero_zona_y_despues_hora():
    hora = next(b for b in _blocks(ROUTER) if b["title"].startswith("1."))["text"]
    assert hora.index("clock timezone COT -5 0") < hora.index("clock set")


def test_domain_lookup_con_espacio_y_dentro_de_configure():
    chunk = next(b for b in _blocks(ROUTER) if b["kind"] == "pegar")["chunks"][0]["text"]
    assert "no ip domain lookup" in chunk and "domain-lookup" not in chunk
    assert chunk.startswith("configure terminal")


def test_vlan_antes_de_su_interfaz():
    titles = [c["title"] for c in next(b for b in _blocks({**SWITCH, "mgmt_if": "vlan10"})
                                       if b["kind"] == "pegar")["chunks"]]
    assert titles.index("Trozo 2: VLAN de gestión") < titles.index("Trozo 3: IP de gestión")


def test_fijo_termina_guardando_y_prestamo_no():
    fijo = next(b for b in _blocks({**ROUTER, "mode": "fijo"}) if b["kind"] == "pegar")["chunks"]
    assert fijo[-1]["text"] == "write memory"
    prestamo = next(b for b in _blocks(ROUTER) if b["kind"] == "pegar")["chunks"]
    assert all("write memory" not in c["text"] for c in prestamo)
