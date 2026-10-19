"""
Pruebas de la Fase 8 (paso 8.2): auditoría encadenada con SHA-256.

Para simular a un atacante que abre el archivo .db con otra herramienta, las
pruebas BORRAN primero los triggers de protección (eso es lo que haría quien
quiera alterar la base sin pasar por la aplicación) y luego modifican datos.
"""
import sqlite3

import pytest

from app.db import GENESIS_HASH, audit, audit_hash, connect, init_db, verify_audit_chain


def _actions(conn, n=5):
    for i in range(n):
        audit(conn, "tester", f"prueba.accion{i}", "devices", i, f"detalle simulado {i}")


def _drop_triggers(conn):
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    conn.execute("DROP TRIGGER IF EXISTS audit_no_delete")


# ---------------------------------------------------------------------------
# 1. La cadena
# ---------------------------------------------------------------------------
def test_cada_registro_apunta_al_anterior(conn):
    _actions(conn)
    rows = conn.execute("SELECT prev_hash, hash FROM audit_log ORDER BY id").fetchall()
    assert rows[0]["prev_hash"] == GENESIS_HASH
    for before, after in zip(rows, rows[1:]):
        assert after["prev_hash"] == before["hash"]
    assert all(len(r["hash"]) == 64 for r in rows)                   # SHA-256 = 64 hex


def test_cadena_integra(conn):
    _actions(conn)
    r = verify_audit_chain(conn)
    assert r["ok"] and r["broken_at"] is None and r["total"] >= 5


def test_separador_evita_ambiguedades():
    # Sin separador, ("ab", "c") y ("a", "bc") darían el mismo texto y el mismo hash
    assert audit_hash("0", "ab", "c", "x", None, None, None, "ok") != \
           audit_hash("0", "a", "bc", "x", None, None, None, "ok")


def test_dos_conexiones_no_bifurcan_la_cadena(app):
    # El receptor UDP y la web escriben con conexiones distintas
    db = app.config["DATABASE_PATH"]
    a, b = connect(db), connect(db)
    for i in range(6):
        audit(a if i % 2 else b, "sistema", "prueba.concurrencia", None, i, "")
    assert verify_audit_chain(a)["ok"]
    a.close(), b.close()


# ---------------------------------------------------------------------------
# 2. Primera capa: la base rechaza modificar o borrar
# ---------------------------------------------------------------------------
def test_trigger_impide_modificar(conn):
    _actions(conn, 1)
    with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
        conn.execute("UPDATE audit_log SET actor = 'otro'")


def test_trigger_impide_borrar(conn):
    _actions(conn, 1)
    with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
        conn.execute("DELETE FROM audit_log")


# ---------------------------------------------------------------------------
# 3. Segunda capa: si alguien salta los triggers, la cadena lo delata
# ---------------------------------------------------------------------------
def test_detecta_registro_modificado(conn):
    _actions(conn)
    target = conn.execute("SELECT id FROM audit_log WHERE action = 'prueba.accion2'").fetchone()["id"]
    _drop_triggers(conn)
    conn.execute("UPDATE audit_log SET actor = 'inocente' WHERE id = ?", (target,))   # borrar huellas
    conn.commit()
    r = verify_audit_chain(conn)
    assert not r["ok"] and r["broken_at"] == target and "alterado" in r["reason"]


def test_detecta_registro_borrado(conn):
    _actions(conn)
    target = conn.execute("SELECT id FROM audit_log WHERE action = 'prueba.accion2'").fetchone()["id"]
    _drop_triggers(conn)
    conn.execute("DELETE FROM audit_log WHERE id = ?", (target,))
    conn.commit()
    r = verify_audit_chain(conn)
    # Se rompe en el registro SIGUIENTE: su prev_hash apunta al que ya no existe
    assert not r["ok"] and r["broken_at"] > target and "borrado" in r["reason"]


def test_recortar_el_final_se_detecta_con_el_ultimo_hash_guardado(conn):
    _actions(conn)
    guardado = verify_audit_chain(conn)["last_hash"]        # anotado en la bitácora
    _drop_triggers(conn)
    conn.execute("DELETE FROM audit_log WHERE id = (SELECT MAX(id) FROM audit_log)")
    conn.commit()
    r = verify_audit_chain(conn)
    # Límite conocido: la cadena que queda es válida...
    assert r["ok"]
    # ...pero ya no termina en el hash que se había guardado: hubo un recorte
    assert r["last_hash"] != guardado


# ---------------------------------------------------------------------------
# 4. Migración: la auditoría anterior a la Fase 8.2 se encadena al arrancar
# ---------------------------------------------------------------------------
def test_migracion_encadena_registros_antiguos(conn):
    _actions(conn)
    _drop_triggers(conn)
    conn.execute("UPDATE audit_log SET prev_hash = NULL, hash = NULL")   # como una base v0.2.1
    conn.commit()
    init_db(conn)
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE hash IS NULL").fetchone()[0] == 0
    assert verify_audit_chain(conn)["ok"]
    with pytest.raises(sqlite3.DatabaseError):                            # y queda protegida otra vez
        conn.execute("DELETE FROM audit_log")


# ---------------------------------------------------------------------------
# 5. API y permisos
# ---------------------------------------------------------------------------
def test_verificar_desde_la_api(role_client, conn):
    c = role_client("auditor")
    r = c.get("/api/audit/verify")
    assert r.status_code == 200 and r.json["ok"] is True
    row = conn.execute("SELECT actor, result FROM audit_log WHERE action = 'audit.verify'").fetchone()
    assert row["actor"] == "auditor" and row["result"] == "ok"


def test_operador_no_puede_verificar(role_client):
    assert role_client("operador").get("/api/audit/verify").status_code == 403


def test_api_reporta_cadena_rota_y_deja_alerta(client, conn):
    _actions(conn)
    _drop_triggers(conn)
    conn.execute("UPDATE audit_log SET detail = 'nada que ver' WHERE action = 'prueba.accion1'")
    conn.commit()
    r = client.get("/api/audit/verify")
    assert r.json["ok"] is False
    row = conn.execute("SELECT result, detail FROM audit_log WHERE action = 'audit.verify'").fetchone()
    assert row["result"] == "alerta" and "CADENA ROTA" in row["detail"]


def test_listado_incluye_el_hash(client):
    rows = client.get("/api/audit").json["rows"]
    assert rows and all(len(r["hash"]) == 64 for r in rows)
