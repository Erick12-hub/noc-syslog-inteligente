"""
Pruebas de la Fase 10.3: aprobación, ejecución, verificación y rollback de cambios.

Los cambios se ejecutan sobre el SIM-CORE-RTR01 en modo simulado: las líneas
aplicadas quedan en sim_device_config y la configuración simulada las refleja.
Una línea que empiece por "simular-error" hace que el equipo simulado responda
"% Invalid input" (para probar el rollback automático).
"""
from datetime import datetime, timedelta, timezone

import pytest

import app.connector as connector
from app.changeexec import expected_lines, missing_lines
from app.connector import apply_config_lines
from app.rules import evaluate

LOCAL = timezone(timedelta(hours=-5))
DESC = "interface GigabitEthernet0/0/1\n description Enlace a ISP de respaldo"
DESC_RB = "interface GigabitEthernet0/0/1\n no description"


def _dev_id(conn, name="SIM-CORE-RTR01"):
    return conn.execute("SELECT id FROM devices WHERE name = ?", (name,)).fetchone()["id"]


def _win(start_h=-0.5, duration=2):
    s = datetime.now(LOCAL).replace(second=0, microsecond=0) + timedelta(hours=start_h)
    return s.strftime("%Y-%m-%dT%H:%M"), (s + timedelta(hours=duration)).strftime("%Y-%m-%dT%H:%M")


def _new_change(op, conn, commands=DESC, rollback=DESC_RB, impact=1, probability=1, window=None,
                verify="show ip interface brief", local_window=("", "")):
    body = {"device_id": _dev_id(conn), "title": "Documentar enlace de respaldo",
            "reason": "El inventario y el equipo deben describir el enlace al ISP", "commands": commands,
            "rollback": rollback, "verify": verify, "impact": impact, "probability": probability,
            "window_start": local_window[0], "window_end": local_window[1]}
    r = op.post("/api/changes", json=body)
    assert r.status_code == 201, r.json
    cid = r.json["id"]
    if window:      # la ventana empieza en el pasado para poder ejecutar ya: se fija directo en la base
        conn.execute("UPDATE change_requests SET window_start = ?, window_end = ? WHERE id = ?", (*window, cid))
        conn.commit()
    return cid


@pytest.fixture
def actors(role_client, conn):
    """Operador que pide, dos administradores que revisan."""
    op = role_client("operador", "erick")
    op.post(f"/api/devices/{_dev_id(conn)}/configs", json={"note": "Línea base"})
    return op, role_client("admin_seguridad", "jefe1"), role_client("admin_seguridad", "jefe2")


def _approved(actors, conn, **kw):
    op, a1, _ = actors
    cid = _new_change(op, conn, **kw)
    assert op.post(f"/api/changes/{cid}/submit").status_code == 200
    assert a1.post(f"/api/changes/{cid}/review", json={"decision": "aprobar",
                                                       "comment": "Revisado: comandos y rollback correctos"}).status_code == 200
    return cid


def _utc_window(start_h=-0.5, duration=2):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    s = now + timedelta(hours=start_h)
    return s.strftime("%Y-%m-%dT%H:%M:%SZ"), (s + timedelta(hours=duration)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# 1. Revisión y separación de funciones
# ---------------------------------------------------------------------------
def test_aprobar_bajo_con_una_revision(actors, conn):
    cid = _approved(actors, conn)
    c = actors[0].get(f"/api/changes/{cid}").json
    assert c["status"] == "aprobado" and c["approved_at"] and c["approvals"][0]["reviewer"] == "jefe1"
    a = conn.execute("SELECT actor, result FROM audit_log WHERE action = 'change.approve'").fetchone()
    assert a["actor"] == "jefe1" and a["result"] == "ok"


def test_nadie_revisa_su_propio_cambio(role_client, conn):
    admin = role_client("admin_seguridad", "jefe1")
    cid = _new_change(admin, conn)
    admin.post(f"/api/changes/{cid}/submit")
    r = admin.post(f"/api/changes/{cid}/review", json={"decision": "aprobar", "comment": "Me apruebo a mí mismo"})
    assert r.status_code == 403 and "Separación de funciones" in r.json["errors"][0]
    assert conn.execute("SELECT result FROM audit_log WHERE action = 'change.review_bloqueado'").fetchone()[0] == "bloqueado"


def test_operador_no_revisa(actors, conn):
    op, _, _ = actors
    cid = _new_change(op, conn)
    op.post(f"/api/changes/{cid}/submit")
    otro = actors[0]
    assert otro.post(f"/api/changes/{cid}/review", json={"decision": "aprobar",
                                                         "comment": "No tengo el rol para esto"}).status_code == 403


def test_alto_necesita_dos_personas(actors, conn):
    op, a1, a2 = actors
    cid = _new_change(op, conn, commands="interface GigabitEthernet0/0/1\n no shutdown",
                      rollback="interface GigabitEthernet0/0/1\n shutdown", impact=3, probability=2,
                      local_window=_win(start_h=24))
    assert op.get(f"/api/changes/{cid}").json["approvals_required"] == 2
    assert op.post(f"/api/changes/{cid}/submit").status_code == 200
    ok = {"decision": "aprobar", "comment": "Revisado el plan y el rollback"}
    a1.post(f"/api/changes/{cid}/review", json=ok)
    assert op.get(f"/api/changes/{cid}").json["status"] == "pendiente"            # 1 de 2
    r = a1.post(f"/api/changes/{cid}/review", json=ok)
    assert r.status_code == 409 and "OTRA persona" in r.json["errors"][0]
    a2.post(f"/api/changes/{cid}/review", json=ok)
    c = op.get(f"/api/changes/{cid}").json
    assert c["status"] == "aprobado" and [x["reviewer"] for x in c["approvals"]] == ["jefe1", "jefe2"]


def test_rechazo_cierra(actors, conn):
    op, a1, _ = actors
    cid = _new_change(op, conn)
    op.post(f"/api/changes/{cid}/submit")
    r = a1.post(f"/api/changes/{cid}/review", json={"decision": "rechazar", "comment": "Falta la verificación"})
    assert r.json["status"] == "rechazado" and "Falta la verificación" in r.json["result"]
    assert op.post(f"/api/changes/{cid}/execute").status_code == 409


@pytest.mark.parametrize("body, status", [
    ({"decision": "aprobar", "comment": "corto"}, 400),
    ({"decision": "quizas", "comment": "Comentario suficiente"}, 400),
])
def test_revision_invalida(actors, conn, body, status):
    op, a1, _ = actors
    cid = _new_change(op, conn)
    op.post(f"/api/changes/{cid}/submit")
    assert a1.post(f"/api/changes/{cid}/review", json=body).status_code == status


def test_solo_se_revisa_lo_pendiente(actors, conn):
    op, a1, _ = actors
    cid = _new_change(op, conn)          # borrador
    assert a1.post(f"/api/changes/{cid}/review", json={"decision": "aprobar",
                                                       "comment": "Todavía es borrador"}).status_code == 409


def test_revisiones_no_se_modifican(actors, conn):
    _approved(actors, conn)
    with pytest.raises(Exception, match="no se pueden modificar"):
        conn.execute("UPDATE change_approvals SET decision = 'rechazado'")
    with pytest.raises(Exception, match="no se pueden borrar"):
        conn.execute("DELETE FROM change_approvals")


# ---------------------------------------------------------------------------
# 2. Ejecución exitosa
# ---------------------------------------------------------------------------
def test_ejecucion_completa(actors, conn):
    op = actors[0]
    cid = _approved(actors, conn)
    r = op.post(f"/api/changes/{cid}/execute")
    assert r.status_code == 200, r.json
    c = r.json
    assert c["status"] == "ejecutado" and c["executed_by"] == "erick" and c["result"] == "Ejecutado y verificado"
    assert [s["step"] for s in c["execution"]] == ["Línea base", "Deriva", "Aplicar", "Verificación",
                                                   "Configuración después"]
    assert all(s["ok"] for s in c["execution"])
    diff = op.get(f"/api/configs/diff?from={c['pre_version_id']}&to={c['post_version_id']}").json
    assert "+ description Enlace a ISP de respaldo" in diff["lines"]
    apply = conn.execute("SELECT command, status FROM device_commands WHERE command LIKE 'configure terminal%'").fetchone()
    assert apply["status"] == "ok" and "2 líneas" in apply["command"]
    acts = [r[0] for r in conn.execute("SELECT action FROM audit_log WHERE entity = 'change_requests'")]
    assert "change.execute" in acts and "change.executed" in acts


def test_cambio_que_ya_estaba_aplicado(actors, conn):
    op = actors[0]
    cid = _approved(actors, conn)
    op.post(f"/api/changes/{cid}/execute")
    cid2 = _approved(actors, conn)            # el mismo cambio otra vez: no cambia nada
    c = op.post(f"/api/changes/{cid2}/execute").json
    assert c["status"] == "ejecutado" and "ya estaba así" in c["execution"][-1]["detail"]


def test_ventana(actors, conn):
    op, a1, _ = actors
    cid = _approved(actors, conn)
    conn.execute("UPDATE change_requests SET window_start = ?, window_end = ? WHERE id = ?", (*_utc_window(2, 1), cid))
    conn.commit()
    r = op.post(f"/api/changes/{cid}/execute")
    assert r.status_code == 409 and "Todavía no empieza" in r.json["errors"][0]
    conn.execute("UPDATE change_requests SET window_start = ?, window_end = ? WHERE id = ?", (*_utc_window(-3, 1), cid))
    conn.commit()
    assert "ya terminó" in op.post(f"/api/changes/{cid}/execute").json["errors"][0]
    conn.execute("UPDATE change_requests SET window_start = ?, window_end = ? WHERE id = ?", (*_utc_window(-0.5, 2), cid))
    conn.commit()
    assert op.post(f"/api/changes/{cid}/execute").json["status"] == "ejecutado"


def test_solo_aprobados_y_auditor_no_ejecuta(actors, role_client, conn):
    op = actors[0]
    cid = _new_change(op, conn)
    assert "Solo se ejecuta un cambio aprobado" in op.post(f"/api/changes/{cid}/execute").json["errors"][0]
    cid2 = _approved(actors, conn)
    assert role_client("auditor").post(f"/api/changes/{cid2}/execute").status_code == 403


def test_comandos_se_revalidan_al_ejecutar(actors, conn):
    op = actors[0]
    cid = _approved(actors, conn)
    conn.execute("UPDATE change_requests SET commands = 'write memory' WHERE id = ?", (cid,))   # alterado por fuera
    conn.commit()
    r = op.post(f"/api/changes/{cid}/execute")
    assert r.status_code == 409 and "prohibido" in " ".join(r.json["errors"])
    assert conn.execute("SELECT COUNT(*) FROM device_commands WHERE command LIKE 'configure terminal%'").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# 3. Fallas, deriva y rollback
# ---------------------------------------------------------------------------
def test_falla_al_aplicar_hace_rollback_automatico(actors, conn):
    op = actors[0]
    cid = _approved(actors, conn, commands=DESC + "\n simular-error de prueba", rollback=DESC_RB)
    c = op.post(f"/api/changes/{cid}/execute").json
    assert c["status"] == "revertido" and "quedó como antes" in c["result"]
    steps = {s["step"]: s for s in c["execution"]}
    assert steps["Aplicar"]["ok"] is False and "Invalid input" in steps["Aplicar"]["detail"]
    assert steps["Comparar con la de antes"]["ok"] is True
    assert conn.execute("SELECT result FROM audit_log WHERE action = 'change.rollback'").fetchone()[0] == "alerta"


def test_rollback_que_no_restaura_abre_incidente(actors, conn):
    op = actors[0]
    cid = _approved(actors, conn, commands=DESC + "\n simular-error", rollback="interface GigabitEthernet0/0/1\n description Otra cosa")
    c = op.post(f"/api/changes/{cid}/execute").json
    assert c["status"] == "fallido" and "no restauró" in c["result"]
    inc = conn.execute("SELECT severity, title FROM incidents WHERE correlation_key = ?", (f"cambio|{cid}",)).fetchone()
    assert inc["severity"] == 2 and "rollback incompleto" in inc["title"]


def test_verificacion_que_falla(actors, conn, monkeypatch):
    op = actors[0]
    cid = _approved(actors, conn)
    real = connector.SimulatedTransport.send
    monkeypatch.setattr(connector.SimulatedTransport, "send", lambda self, c: (
        "% Invalid input detected" if c == "show ip interface brief" else real(self, c)))
    c = op.post(f"/api/changes/{cid}/execute").json
    assert c["status"] == "revertido" and any(s["step"] == "Verificación" and not s["ok"] for s in c["execution"])


def test_deriva_no_aplica_nada(actors, conn):
    op = actors[0]
    cid = _approved(actors, conn)
    # Alguien cambia el equipo por fuera DESPUÉS de aprobar (en simulado: la descripción del inventario)
    op.post(f"/api/devices/{_dev_id(conn)}/interfaces",
            json={"name": "GigabitEthernet0/0/2", "status": "down", "description": "Cambio sin permiso"})
    c = op.post(f"/api/changes/{cid}/execute").json
    assert c["status"] == "fallido" and "deriva" in c["result"]
    assert conn.execute("SELECT COUNT(*) FROM device_commands WHERE command LIKE 'configure terminal%'").fetchone()[0] == 0
    assert conn.execute("SELECT severity FROM incidents WHERE correlation_key = ?", (f"cambio|{cid}",)).fetchone()[0] == 3


def test_otro_cambio_del_noc_no_es_deriva(actors, conn):
    op = actors[0]
    a = _approved(actors, conn)
    b = _approved(actors, conn, commands="interface GigabitEthernet0/0/2\n description Reserva",
                  rollback="interface GigabitEthernet0/0/2\n no description")
    assert op.post(f"/api/changes/{a}/execute").json["status"] == "ejecutado"
    c = op.post(f"/api/changes/{b}/execute").json          # su línea base era la de antes de 'a'
    assert c["status"] == "ejecutado"
    assert f"solo por el cambio #{a}" in next(s["detail"] for s in c["execution"] if s["step"] == "Deriva")


def test_otro_equipo_fisico_no_aplica(actors, conn, monkeypatch):
    op = actors[0]
    cid = _approved(actors, conn)
    calls = {"n": 0}
    real = connector.SimulatedTransport.send

    def send(self, c):        # la línea base sale del equipo bueno; luego responde otro
        out = real(self, c)
        if c == "show version":
            calls["n"] += 1
            if calls["n"] > 1:
                out = out.replace("FGL2601SIM1", "FGL0000OTRO")
        return out
    monkeypatch.setattr(connector.SimulatedTransport, "send", send)
    c = op.post(f"/api/changes/{cid}/execute").json
    assert c["status"] == "fallido" and "No se hizo rollback" in c["result"]
    assert "OTRO equipo físico" in next(s["detail"] for s in c["execution"] if s["step"] == "Aplicar")
    assert not any(s["step"] == "Rollback" for s in c["execution"])
    assert conn.execute("SELECT severity FROM incidents WHERE correlation_key = ?", (f"cambio|{cid}",)).fetchone()[0] == 2


def test_no_se_puede_leer_la_linea_base(actors, conn, monkeypatch):
    op = actors[0]
    cid = _approved(actors, conn)
    real = connector.SimulatedTransport.send
    monkeypatch.setattr(connector.SimulatedTransport, "send",
                        lambda self, c: "% error" if c == "show running-config" else real(self, c))
    r = op.post(f"/api/changes/{cid}/execute")
    assert r.status_code == 502 and op.get(f"/api/changes/{cid}").json["status"] == "aprobado"


def test_rollback_manual(actors, conn):
    op = actors[0]
    cid = _approved(actors, conn)
    op.post(f"/api/changes/{cid}/execute")
    assert op.post(f"/api/changes/{cid}/rollback", json={"comment": "corto"}).status_code == 400
    c = op.post(f"/api/changes/{cid}/rollback", json={"comment": "El ISP pidió dejar la interfaz sin descripción"}).json
    assert c["status"] == "revertido" and "manual" in c["result"]
    assert op.post(f"/api/changes/{cid}/rollback", json={"comment": "Otra vez por error"}).status_code == 409


# ---------------------------------------------------------------------------
# 4. Regla "fuera de horario" y cambios autorizados
# ---------------------------------------------------------------------------
NIGHT = datetime(2026, 10, 24, 1, 30, tzinfo=timezone.utc)      # 8:30 p. m. en Colombia


def _cfg_event(conn):
    return {"id": 0, "device_id": _dev_id(conn), "source_ip": "192.0.2.1", "authorized": 1,
            "message": "Configured from console by noc on vty0", "mnemonic": "SYS-5-CONFIG_I"}


def test_fuera_de_horario_sin_cambio_aprobado(conn):
    assert "cambio_fuera_de_horario" in evaluate(conn, _cfg_event(conn), NIGHT)


def test_cambio_aprobado_en_ejecucion_es_autorizado(actors, conn):
    cid = _approved(actors, conn)
    conn.execute("UPDATE change_requests SET status = 'en_ejecucion' WHERE id = ?", (cid,))
    conn.commit()
    hits = evaluate(conn, _cfg_event(conn), NIGHT)
    assert "cambio_autorizado" in hits and "cambio_fuera_de_horario" not in hits


def test_poco_despues_del_cambio_sigue_autorizado(actors, conn):
    cid = _approved(actors, conn)
    actors[0].post(f"/api/changes/{cid}/execute")
    hits = evaluate(conn, _cfg_event(conn), datetime.now(timezone.utc) + timedelta(minutes=2))
    assert hits == ["cambio_autorizado"]
    later = evaluate(conn, _cfg_event(conn), datetime.now(timezone.utc) + timedelta(minutes=30))
    assert "cambio_autorizado" not in later


# ---------------------------------------------------------------------------
# 5. Modelo de configuración simulado y verificación de líneas
# ---------------------------------------------------------------------------
BASE = "hostname R1\n!\ninterface Gi0/1\n no ip address\n shutdown\n negotiation auto\n!\nlogging trap informational\nend\n"


def test_modelo_simulado_aplica_y_revierte():
    changed = apply_config_lines(BASE, ["interface Gi0/1", " description WAN", " ip address 10.0.0.1 255.255.255.252",
                                        " no shutdown", "logging trap warnings"])
    assert " description WAN" in changed and " shutdown" not in changed and "logging trap warnings" in changed
    back = apply_config_lines(changed, ["interface Gi0/1", " shutdown", " no ip address", " no description",
                                        "logging trap informational"])
    assert back == BASE


def test_lineas_esperadas():
    cmds = ["interface Gi0/1", "  description   WAN", " no shutdown", "exit"]
    assert expected_lines(cmds) == ["interface Gi0/1", "description WAN"]
    assert missing_lines("interface Gi0/1\n description WAN\n", cmds) == []
    assert missing_lines("interface Gi0/1\n", cmds) == ["description WAN"]
