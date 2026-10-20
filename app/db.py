"""
Acceso a la base de datos SQLite.

- get_db():   conexión reutilizada durante una petición HTTP de Flask.
- connect():  conexión independiente (para scripts y el receptor UDP).
- init_db():  crea las tablas desde schema.sql y carga el catálogo de severidades.
- audit():    registra una acción en la tabla de auditoría (encadenada, Fase 8.2).
- verify_audit_chain(): comprueba que nadie alteró ni borró registros.
"""
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"

# Catálogo de severidades RFC 5424.
# Última columna = política inicial: severidades 0-3 generan incidente.
SEVERITIES = [
    (0, "emerg",   "Emergency",     "El sistema no es utilizable", 1),
    (1, "alert",   "Alert",         "Se requiere acción inmediata", 1),
    (2, "crit",    "Critical",      "Condición crítica", 1),
    (3, "err",     "Error",         "Condición de error", 1),
    (4, "warning", "Warning",       "Condición de advertencia", 0),
    (5, "notice",  "Notice",        "Condición normal pero significativa", 0),
    (6, "info",    "Informational", "Mensaje informativo", 0),
    (7, "debug",   "Debug",         "Mensaje de depuración", 0),
]


def now_iso() -> str:
    """Fecha y hora actual en UTC, formato ISO 8601 (ej. 2026-10-02T19:30:00Z)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path) -> sqlite3.Connection:
    """Abre una conexión SQLite con filas tipo diccionario y claves foráneas activas."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row          # permite row["columna"]
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite las trae apagadas por defecto
    # Fase 7.4 - optimización:
    # WAL (Write-Ahead Logging): el receptor UDP puede ESCRIBIR eventos mientras
    # la web los LEE, sin bloquearse. Sin WAL, una lectura larga frena la ingesta.
    # Crea dos archivos auxiliares junto a la base: noc.db-wal y noc.db-shm.
    conn.execute("PRAGMA journal_mode = WAL")
    # Si otra conexión está escribiendo, esperar hasta 5 s en vez de fallar.
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def get_db() -> sqlite3.Connection:
    """Conexión de la petición actual (se crea una sola vez por petición)."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(_exc=None):
    """Cierra la conexión al terminar la petición."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Columnas agregadas después de la Fase 1. "CREATE TABLE IF NOT EXISTS" no
# modifica tablas que ya existen, así que se agregan con ALTER TABLE.
# Esto es una MIGRACIÓN sencilla: actualiza la base sin borrar los datos.
MIGRATIONS = [
    ("syslog_events", "mnemonic", "TEXT"),
    ("syslog_events", "flags", "TEXT"),
    ("incidents", "correlation_key", "TEXT"),
    ("incidents", "event_count", "INTEGER NOT NULL DEFAULT 1"),
    ("incidents", "last_event_at", "TEXT"),
    # Fase 7: puerto/interfaz en eventos y tiempos de respuesta en incidentes.
    # (ALTER TABLE no admite CHECK con rango en columnas nuevas de forma segura
    #  en todas las versiones; el rango 1-65535 lo valida el parser antes de guardar.)
    ("syslog_events", "interface", "TEXT"),
    ("syslog_events", "src_port", "INTEGER"),
    ("syslog_events", "dst_port", "INTEGER"),
    ("syslog_events", "event_time_utc", "TEXT"),
    ("incidents", "assigned_at", "TEXT"),
    ("incidents", "started_at", "TEXT"),
    # Fase 8.2: auditoría encadenada
    ("audit_log", "prev_hash", "TEXT"),
    ("audit_log", "hash", "TEXT"),
    # Fase 9.1: conexión con los equipos e identidad física
    ("devices", "connection_mode", "TEXT NOT NULL DEFAULT 'ninguno'"),
    ("devices", "platform", "TEXT"),
    ("devices", "console_port", "TEXT"),
    ("devices", "serial_number", "TEXT"),
    ("devices", "detected_model", "TEXT"),
    ("devices", "detected_version", "TEXT"),
    ("devices", "host_key_fp", "TEXT"),
    ("devices", "last_identified_at", "TEXT"),
]


def _migrate(conn: sqlite3.Connection):
    for table, column, decl in MIGRATIONS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


# Fase 7.4: índices COMPUESTOS para las consultas más frecuentes.
# Se crean DESPUÉS de las migraciones porque algunos usan columnas nuevas
# (si estuvieran en schema.sql fallarían en una base del Corte 2).
# Un índice es como el índice de un libro: SQLite salta directo a las filas
# que necesita en lugar de leer la tabla completa.
INDEXES = [
    # Filtro "Equipo" del listado de eventos + rango de fechas
    ("idx_events_device_time", "syslog_events(device_id, received_at)"),
    # Dashboard y filtro de severidad + rango de fechas
    ("idx_events_sev_time", "syslog_events(severity, received_at)"),
    # Deduplicación: misma huella en los últimos 60 s (se consulta con CADA mensaje)
    ("idx_events_fp_time", "syslog_events(fingerprint, received_at)"),
    # Filtro de interfaz (Fase 7.1)
    ("idx_events_interface", "syslog_events(interface)"),
    # Correlación: incidente abierto con la misma clave (se consulta con cada evento grave)
    ("idx_incidents_corr", "incidents(correlation_key, status)"),
    # Filtro "Actor" de la auditoría
    ("idx_audit_actor", "audit_log(actor, ts)"),
]
# Índices reemplazados por uno compuesto más útil
OBSOLETE_INDEXES = ["idx_events_fp"]


def _ensure_indexes(conn: sqlite3.Connection):
    for name in OBSOLETE_INDEXES:
        conn.execute(f"DROP INDEX IF EXISTS {name}")
    for name, target in INDEXES:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")


def init_db(conn: sqlite3.Connection):
    """Crea las tablas (si no existen), aplica migraciones y carga las severidades."""
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    _migrate(conn)
    _ensure_indexes(conn)
    _chain_existing_audit(conn)      # Fase 8.2: encadena registros anteriores (una sola vez)
    _protect_audit(conn)             # Fase 8.2: triggers de solo inserción
    conn.executemany(
        "INSERT OR REPLACE INTO severities "
        "(code, keyword, name, description, creates_incident) VALUES (?, ?, ?, ?, ?)",
        SEVERITIES,
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Fase 8.2: AUDITORÍA ENCADENADA
#
#   registro 1:  hash1 = SHA-256( GENESIS | datos1 )
#   registro 2:  hash2 = SHA-256( hash1   | datos2 )
#   registro 3:  hash3 = SHA-256( hash2   | datos3 )
#
# Cada registro "contiene" la huella del anterior. Si alguien cambia una letra
# del registro 2, su hash ya no coincide; y si borra el registro 2, el
# registro 3 apunta a un hash que no existe. La verificación lo detecta.
#
# Dos capas de protección:
#   1) Triggers de SQLite: la base RECHAZA cualquier UPDATE o DELETE sobre
#      audit_log (ni la propia aplicación puede modificarla).
#   2) La cadena: si alguien salta los triggers (abre el archivo .db con otra
#      herramienta), la alteración queda en evidencia al verificar.
# ---------------------------------------------------------------------------
GENESIS_HASH = "0" * 64      # "hash anterior" del primer registro


def audit_hash(prev_hash, ts, actor, action, entity, entity_id, detail, result) -> str:
    """SHA-256 de los datos del registro unidos al hash anterior (formato fijo)."""
    fields = [prev_hash, ts, actor, action, entity, entity_id, detail, result]
    # "\x1f" (separador de unidad) evita ambigüedades: ("ab","c") != ("a","bc")
    payload = "\x1f".join("" if f is None else str(f) for f in fields)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _last_hash(conn) -> str:
    row = conn.execute("SELECT hash FROM audit_log WHERE hash IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    return row[0] if row else GENESIS_HASH


def audit(conn, actor, action, entity=None, entity_id=None, detail=None, result="ok"):
    """Agrega un registro ENCADENADO de auditoría. Nunca se modifica ni borra después."""
    # BEGIN IMMEDIATE toma el bloqueo de escritura ANTES de leer el último hash:
    # así el receptor UDP y la web no pueden encadenar dos registros al mismo
    # "anterior" al mismo tiempo (la cadena se bifurcaría).
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    ts = now_iso()
    prev = _last_hash(conn)
    digest = audit_hash(prev, ts, actor, action, entity, entity_id, detail, result)
    conn.execute(
        "INSERT INTO audit_log (ts, actor, action, entity, entity_id, detail, result, prev_hash, hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ts, actor, action, entity, entity_id, detail, result, prev, digest),
    )
    conn.commit()


def _chain_existing_audit(conn):
    """Migración: los registros creados antes de la Fase 8.2 reciben su hash, en orden."""
    pending = conn.execute("SELECT COUNT(*) FROM audit_log WHERE hash IS NULL").fetchone()[0]
    if not pending:
        return
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")    # solo durante la migración
    prev = GENESIS_HASH
    for r in conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall():
        if r["hash"] is None:
            digest = audit_hash(prev, r["ts"], r["actor"], r["action"], r["entity"],
                                r["entity_id"], r["detail"], r["result"])
            conn.execute("UPDATE audit_log SET prev_hash = ?, hash = ? WHERE id = ?", (prev, digest, r["id"]))
            prev = digest
        else:
            prev = r["hash"]
    conn.commit()


def _protect_audit(conn):
    """Triggers: la base de datos rechaza modificar o borrar la auditoría."""
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'La auditoría es de solo inserción: no se puede modificar'); END;
        CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'La auditoría es de solo inserción: no se puede borrar'); END;
    """)


def verify_audit_chain(conn) -> dict:
    """
    Recorre TODA la auditoría y recalcula cada hash.

    Devuelve {"ok", "total", "last_id", "last_hash", "broken_at", "reason"}.
    broken_at = id del primer registro donde la cadena se rompe:
      - "registro alterado": su contenido ya no produce su hash.
      - "registro anterior borrado o alterado": su prev_hash no es el hash del anterior.
    Límite conocido: si se borran los ÚLTIMOS registros, la cadena que queda es
    válida. Por eso se muestra el último hash: guardarlo aparte (bitácora,
    informe) permite comprobar luego que la cadena no fue recortada.
    """
    prev = GENESIS_HASH
    total, last_id = 0, None
    for r in conn.execute("SELECT * FROM audit_log ORDER BY id"):
        total += 1
        if r["prev_hash"] != prev:
            return {"ok": False, "total": total, "broken_at": r["id"], "last_id": last_id, "last_hash": prev,
                    "reason": "registro anterior borrado o alterado (el enlace no coincide)"}
        expected = audit_hash(prev, r["ts"], r["actor"], r["action"], r["entity"],
                              r["entity_id"], r["detail"], r["result"])
        if r["hash"] != expected:
            return {"ok": False, "total": total, "broken_at": r["id"], "last_id": last_id, "last_hash": prev,
                    "reason": "registro alterado (su contenido no coincide con su hash)"}
        prev, last_id = r["hash"], r["id"]
    return {"ok": True, "total": total, "broken_at": None, "last_id": last_id, "last_hash": prev, "reason": None}
