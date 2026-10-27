"""
Pruebas de la Fase 12: respaldo, verificación y restauración de la base.

Todo ocurre en carpetas TEMPORALES: nunca se toca data/noc.db ni data/respaldos.
"""
import json
import sqlite3

import pytest

from app.backup import create_backup, list_backups, prune, restore_backup, verify_backup
from app.config import Config
from app.db import audit, connect, verify_audit_chain


@pytest.fixture
def db(app):
    return app.config["DATABASE_PATH"]


@pytest.fixture
def dest(tmp_path):
    return tmp_path / "respaldos"


def _audit_count(path):
    c = connect(path)
    try:
        return c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    finally:
        c.close()


def _add_event(path, text="evento SIM"):
    c = connect(path)
    try:
        audit(c, "tester", "prueba.evento", detail=text)
    finally:
        c.close()


def test_backup_creates_db_and_manifest(db, dest):
    r = create_backup(db, dest, "tester", "antes de la demo")
    assert (dest / r["file"]).is_file()
    m = json.loads((dest / r["file"]).with_suffix(".json").read_text(encoding="utf-8"))
    assert m["sha256"] == r["sha256"] and len(m["sha256"]) == 64
    assert m["integrity"] == "ok" and m["audit_chain_ok"] is True
    assert m["created_by"] == "tester" and m["note"] == "antes de la demo"
    assert m["counts"]["devices"] > 0                 # incluye los equipos SIM


def test_backup_is_audited_in_the_live_database(db, dest):
    create_backup(db, dest, "tester")
    c = connect(db)
    row = c.execute("SELECT actor, result, detail FROM audit_log WHERE action = 'backup.create'").fetchone()
    c.close()
    assert row["actor"] == "tester" and row["result"] == "ok" and "sha256" in row["detail"]


def test_backup_file_is_self_contained(db, dest):
    r = create_backup(db, dest, "tester")
    assert not (dest / (r["file"] + "-wal")).exists()
    assert not (dest / (r["file"] + "-shm")).exists()


def test_verify_ok_and_verification_does_not_modify_file(db, dest):
    r = create_backup(db, dest, "tester")
    before = (dest / r["file"]).read_bytes()
    v = verify_backup(dest / r["file"])
    assert v["ok"] and v["errors"] == []
    assert (dest / r["file"]).read_bytes() == before   # abrir en solo lectura no lo cambia


def test_verify_detects_modified_file(db, dest):
    r = create_backup(db, dest, "tester")
    path = dest / r["file"]
    c = sqlite3.connect(path)
    c.execute("UPDATE devices SET location = 'alterado' WHERE id = 1")
    c.commit()
    c.close()
    v = verify_backup(path)
    assert not v["ok"]
    assert any("SHA-256" in e for e in v["errors"])


def test_verify_detects_tampered_audit_even_with_new_manifest(db, dest):
    """Aunque alguien recalcule el manifiesto, la cadena de auditoría delata el cambio."""
    _add_event(db, "registro original")
    r = create_backup(db, dest, "tester")
    path = dest / r["file"]
    c = sqlite3.connect(path)
    c.execute("DROP TRIGGER IF EXISTS audit_log_no_update")
    for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_log'"
                             ).fetchall():
        c.execute(f'DROP TRIGGER "{name}"')
    c.execute("UPDATE audit_log SET detail = 'alterado' WHERE action = 'prueba.evento'")
    c.commit()
    c.close()
    from app.backup import _sha256
    mpath = path.with_suffix(".json")
    m = json.loads(mpath.read_text(encoding="utf-8"))
    m["sha256"] = _sha256(path)
    mpath.write_text(json.dumps(m), encoding="utf-8")
    v = verify_backup(path)
    assert not v["ok"]
    assert any("auditoría" in e.lower() for e in v["errors"])


def test_verify_detects_corrupt_file(db, dest):
    r = create_backup(db, dest, "tester")
    path = dest / r["file"]
    path.write_bytes(b"esto no es una base de datos" * 100)
    v = verify_backup(path)
    assert not v["ok"]


def test_verify_requires_manifest(db, dest):
    r = create_backup(db, dest, "tester")
    (dest / r["file"]).with_suffix(".json").unlink()
    v = verify_backup(dest / r["file"])
    assert not v["ok"] and any("manifiesto" in e for e in v["errors"])


def test_verify_missing_file(dest):
    v = verify_backup(dest / "no_existe.db")
    assert not v["ok"]


def test_list_backups_shows_state(db, dest):
    create_backup(db, dest, "tester", kind="manual")
    r2 = create_backup(db, dest, "tester", kind="manual")
    (dest / r2["file"]).write_bytes(b"x" * 10)
    items = list_backups(dest)
    assert len(items) == 2
    by_file = {i["file"]: i for i in items}
    assert by_file[r2["file"]]["ok"] is False
    assert sum(1 for i in items if i["ok"]) == 1


def test_retention_keeps_last_n(db, dest, monkeypatch):
    monkeypatch.setattr(Config, "BACKUP_KEEP", 3)
    for _ in range(5):
        create_backup(db, dest, "tester")
    assert len(list(dest.glob("noc_*.db"))) == 3
    assert len(list(dest.glob("noc_*.json"))) == 3


def test_prune_removes_manifest_too(db, dest):
    for _ in range(3):
        create_backup(db, dest, "tester")
    removed = prune(dest, keep=1)
    assert len(removed) == 2
    assert len(list(dest.glob("*.json"))) == 1


def test_restore_requires_confirmation(db, dest):
    r = create_backup(db, dest, "tester")
    out = restore_backup(dest / r["file"], db, dest, "tester", confirm=False)
    assert not out["ok"] and "confirmar" in out["errors"][0]


def test_restore_brings_back_previous_state(db, dest):
    r = create_backup(db, dest, "tester")
    n_before = _audit_count(db)
    c = connect(db)
    c.execute("DELETE FROM devices WHERE name = 'SIM-EDGE-FW01'")   # "accidente" después del respaldo
    c.commit()
    c.close()
    out = restore_backup(dest / r["file"], db, dest, "tester", confirm=True)
    assert out["ok"]
    c = connect(db)
    assert c.execute("SELECT COUNT(*) FROM devices WHERE name = 'SIM-EDGE-FW01'").fetchone()[0] == 1
    assert verify_audit_chain(c)["ok"]
    last = c.execute("SELECT action, result FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    c.close()
    assert last["action"] == "backup.restore" and last["result"] == "alerta"
    # el respaldo NO contiene su propio registro 'backup.create' (se escribe después de copiar):
    # trae n_before - 1 registros y se suma el de la restauración
    assert _audit_count(db) == n_before


def test_restore_takes_safety_backup_first(db, dest):
    r = create_backup(db, dest, "tester")
    _add_event(db, "dato posterior al respaldo")
    out = restore_backup(dest / r["file"], db, dest, "tester", confirm=True)
    assert out["safety_backup"]
    safety = verify_backup(out["safety_backup"])
    assert safety["ok"] and safety["manifest"]["kind"] == "seguridad"
    # el respaldo de seguridad conserva el dato que la restauración quitó
    from pathlib import Path
    c = sqlite3.connect(Path(out["safety_backup"]).resolve().as_uri() + "?mode=ro", uri=True)
    assert c.execute("SELECT COUNT(*) FROM audit_log WHERE detail = 'dato posterior al respaldo'").fetchone()[0] == 1
    c.close()


def test_restore_refuses_unverified_backup(db, dest):
    r = create_backup(db, dest, "tester")
    path = dest / r["file"]
    c = sqlite3.connect(path)
    c.execute("UPDATE devices SET location = 'alterado'")
    c.commit()
    c.close()
    _add_event(db, "estado actual")
    out = restore_backup(path, db, dest, "tester", confirm=True)
    assert not out["ok"] and "NO se restauró" in out["errors"][0]
    c = connect(db)
    assert c.execute("SELECT COUNT(*) FROM audit_log WHERE detail = 'estado actual'").fetchone()[0] == 1
    c.close()


def test_backup_while_writing_is_consistent(db, dest):
    """Respaldo con otra conexión escribiendo: la copia es consistente (API de respaldo de SQLite)."""
    import threading
    stop = threading.Event()

    def writer():
        c = connect(db)
        try:
            i = 0
            while not stop.is_set() and i < 200:
                audit(c, "tester", "prueba.escritura", detail=f"n={i}")
                i += 1
        finally:
            c.close()

    t = threading.Thread(target=writer)
    t.start()
    try:
        r = create_backup(db, dest, "tester")
    finally:
        stop.set()
        t.join()
    assert verify_backup(dest / r["file"])["ok"]


def test_paths_with_spaces_and_accents(tmp_path):
    """La carpeta del proyecto en Windows tiene espacios (SEMESTRE 5, GESTION DE REDES)."""
    from app.db import init_db
    base = tmp_path / "SEMESTRE 5" / "GESTIÓN DE REDES"
    base.mkdir(parents=True)
    c = connect(base / "noc.db")
    init_db(c)
    c.close()
    r = create_backup(base / "noc.db", base / "respaldos", "tester")
    assert verify_backup(base / "respaldos" / r["file"])["ok"]
    assert restore_backup(base / "respaldos" / r["file"], base / "noc.db", base / "respaldos", "tester",
                          confirm=True)["ok"]


def test_backup_folder_is_ignored_by_git():
    from pathlib import Path
    gitignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "data/respaldos/" in gitignore


def test_cli_backup_commands(app, tmp_path, monkeypatch, capsys):
    import manage
    monkeypatch.setattr(Config, "DATABASE_PATH", app.config["DATABASE_PATH"])
    monkeypatch.setattr(Config, "BACKUP_DIR", tmp_path / "cli_respaldos")
    manage.cmd_backup("prueba cli")
    out = capsys.readouterr().out
    assert "[OK] Respaldo creado" in out and "SHA-256" in out
    name = next((tmp_path / "cli_respaldos").glob("noc_*.db")).name
    manage.cmd_backups()
    assert "íntegro" in capsys.readouterr().out
    manage.cmd_verify_backup(name)
    assert "[OK] Respaldo ÍNTEGRO" in capsys.readouterr().out
    manage.cmd_restore(name, False)
    assert "--confirmar" in capsys.readouterr().out
    manage.cmd_restore(name, True)
    out = capsys.readouterr().out
    assert "[OK] Base restaurada" in out and "seguridad" in out
