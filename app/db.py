"""
Acceso a la base de datos SQLite.

- get_db():   conexión reutilizada durante una petición HTTP de Flask.
- connect():  conexión independiente (para scripts y el receptor UDP).
- init_db():  crea las tablas desde schema.sql y carga el catálogo de severidades.
- audit():    registra una acción en la tabla de auditoría.
"""
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
    conn.executemany(
        "INSERT OR REPLACE INTO severities "
        "(code, keyword, name, description, creates_incident) VALUES (?, ?, ?, ?, ?)",
        SEVERITIES,
    )
    conn.commit()


def audit(conn, actor, action, entity=None, entity_id=None, detail=None, result="ok"):
    """Agrega un registro de auditoría. Nunca se modifica ni borra después."""
    conn.execute(
        "INSERT INTO audit_log (ts, actor, action, entity, entity_id, detail, result) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now_iso(), actor, action, entity, entity_id, detail, result),
    )
    conn.commit()
