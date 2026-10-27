"""
Fase 12: RESPALDO Y RESTAURACIÓN de la base del NOC, con verificación.

    python manage.py backup [--nota "..."]        Crea un respaldo verificado
    python manage.py backups                      Lista los respaldos y su estado
    python manage.py verify-backup ARCHIVO        Verifica un respaldo
    python manage.py restore ARCHIVO --confirmar  Restaura (con respaldo previo de seguridad)

CÓMO SE RESPALDA
    Con la API de respaldo de SQLite (sqlite3.backup): copia página por página
    una foto CONSISTENTE de la base aunque la web y el receptor estén escribiendo.
    Copiar el archivo .db a mano con WAL activo puede dejar una copia incompleta.
    Cada respaldo lleva un MANIFIESTO (.json) con su huella SHA-256, el tamaño,
    los registros por tabla y el último hash de la auditoría encadenada.

QUÉ SE VERIFICA (al crear, al listar y ANTES de restaurar)
    1. La huella SHA-256 del archivo coincide con la del manifiesto (no fue
       modificado ni se dañó al copiarlo).
    2. PRAGMA integrity_check = ok (la base no está corrupta).
    3. La cadena de auditoría del respaldo está íntegra.
    Si algo falla, el respaldo NO se restaura.

RESTAURAR
    Antes de reemplazar la base actual se toma un respaldo de SEGURIDAD de ella:
    si la restauración no era la correcta, se puede volver atrás. Se exige
    --confirmar. Detenga serve.py y el receptor antes de restaurar.

Retención: se guardan los últimos BACKUP_KEEP respaldos (los de seguridad también cuentan).
Los respaldos viven en data/respaldos/ (fuera de GitHub: tienen datos de operación).
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import APP_VERSION
from .config import Config
from .db import audit, connect, verify_audit_chain

MANIFEST_SUFFIX = ".json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _open_ro(path: Path) -> sqlite3.Connection:
    """Solo lectura e 'inmutable': verificar NO modifica el archivo (ni crea -wal/-shm)."""
    # as_uri() codifica espacios y tildes de la ruta (p. ej. "SEMESTRE 5\GESTION DE REDES" en Windows)
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _inspect(path: Path) -> dict:
    conn = _open_ro(path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
        chain = verify_audit_chain(conn) if "audit_log" in tables else {"ok": False, "total": 0, "last_id": None,
                                                                       "last_hash": None, "reason": "sin auditoría"}
    finally:
        conn.close()
    return {"integrity": integrity, "counts": counts, "chain": chain}


def backup_dir() -> Path:
    return Path(Config.BACKUP_DIR)


def create_backup(db_path, dest_dir, user: str, note: str = "", kind: str = "manual") -> dict:
    """Crea un respaldo consistente, lo verifica y escribe su manifiesto."""
    db_path, dest_dir = Path(db_path), Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
    target = dest_dir / f"noc_{stamp}_{kind}.db"
    src = sqlite3.connect(db_path, timeout=10)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)                                    # foto consistente, aunque haya escrituras
        dst.execute("PRAGMA journal_mode = DELETE")        # archivo autónomo (sin -wal/-shm)
        dst.commit()
    finally:
        dst.close()
        src.close()
    info = _inspect(target)
    manifest = {
        "file": target.name, "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_by": user, "kind": kind, "note": (note or "")[:200], "app_version": APP_VERSION,
        "size_bytes": target.stat().st_size, "sha256": _sha256(target),
        "integrity": info["integrity"], "counts": info["counts"],
        "audit_last_id": info["chain"]["last_id"], "audit_last_hash": info["chain"]["last_hash"],
        "audit_chain_ok": info["chain"]["ok"],
    }
    target.with_suffix(MANIFEST_SUFFIX).write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                                   encoding="utf-8")
    conn = connect(db_path)
    try:
        audit(conn, user, "backup.create", "backups", None,
              f"{target.name} · {manifest['size_bytes']} bytes · sha256 {manifest['sha256'][:12]} · "
              f"auditoría hasta el registro {manifest['audit_last_id']} · tipo {kind}"
              + (f" · {note[:80]}" if note else ""),
              "ok" if manifest["integrity"] == "ok" and manifest["audit_chain_ok"] else "alerta")
    finally:
        conn.close()
    prune(dest_dir)
    return {"path": str(target), **manifest}


def verify_backup(path) -> dict:
    """Comprueba huella, integridad y cadena. Devuelve {ok, errors, manifest, ...}."""
    path = Path(path)
    errors = []
    if not path.is_file():
        return {"ok": False, "errors": [f"No existe el archivo {path}"], "manifest": None}
    mpath = path.with_suffix(MANIFEST_SUFFIX)
    manifest = None
    if not mpath.is_file():
        errors.append("Falta el manifiesto (.json): no se puede comprobar la huella del respaldo")
    else:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        if _sha256(path) != manifest.get("sha256"):
            errors.append("La huella SHA-256 NO coincide: el archivo fue modificado o se dañó")
    try:
        info = _inspect(path)
    except sqlite3.DatabaseError as e:
        return {"ok": False, "errors": errors + [f"No es una base SQLite válida ({e})"], "manifest": manifest}
    if info["integrity"] != "ok":
        errors.append(f"integrity_check: {info['integrity']}")
    if not info["chain"]["ok"]:
        errors.append(f"Cadena de auditoría ROTA en el registro {info['chain'].get('broken_at')}")
    return {"ok": not errors, "errors": errors, "manifest": manifest, "counts": info["counts"],
            "audit_last_id": info["chain"]["last_id"], "audit_last_hash": info["chain"]["last_hash"]}


def list_backups(dest_dir) -> list[dict]:
    dest_dir = Path(dest_dir)
    out = []
    for db in sorted(dest_dir.glob("noc_*.db"), reverse=True):
        v = verify_backup(db)
        m = v["manifest"] or {}
        out.append({"file": db.name, "path": str(db), "created_at": m.get("created_at"), "kind": m.get("kind"),
                    "created_by": m.get("created_by"), "size_bytes": db.stat().st_size,
                    "audit_last_id": v.get("audit_last_id"), "ok": v["ok"], "errors": v["errors"],
                    "note": m.get("note")})
    return out


def prune(dest_dir, keep: int | None = None) -> list[str]:
    """Retención: deja los últimos 'keep' respaldos (con su manifiesto)."""
    keep = keep or Config.BACKUP_KEEP
    removed = []
    for db in sorted(Path(dest_dir).glob("noc_*.db"), reverse=True)[keep:]:
        for p in (db, db.with_suffix(MANIFEST_SUFFIX)):
            if p.exists():
                p.unlink()
        removed.append(db.name)
    return removed


def restore_backup(backup_path, db_path, dest_dir, user: str, confirm: bool = False) -> dict:
    """Restaura un respaldo VERIFICADO, previo respaldo de seguridad de la base actual."""
    backup_path, db_path = Path(backup_path), Path(db_path)
    if not confirm:
        return {"ok": False, "errors": ["Restaurar REEMPLAZA la base actual: repita con --confirmar"]}
    v = verify_backup(backup_path)
    if not v["ok"]:
        return {"ok": False, "errors": ["El respaldo no pasó la verificación: NO se restauró"] + v["errors"]}
    safety = None
    if db_path.exists():
        safety = create_backup(db_path, dest_dir, user, f"antes de restaurar {backup_path.name}", "seguridad")
    src = _open_ro(backup_path)
    dst = sqlite3.connect(db_path, timeout=10)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()
    conn = connect(db_path)
    try:
        chain = verify_audit_chain(conn)
        audit(conn, user, "backup.restore", "backups", None,
              f"restaurado {backup_path.name} (auditoría hasta el registro {v['audit_last_id']})"
              + (f" · respaldo de seguridad previo: {Path(safety['path']).name}" if safety else ""), "alerta")
    finally:
        conn.close()
    return {"ok": chain["ok"], "errors": [] if chain["ok"] else ["La cadena quedó rota tras restaurar"],
            "restored": backup_path.name, "safety_backup": safety["path"] if safety else None,
            "audit_last_id": v["audit_last_id"]}
