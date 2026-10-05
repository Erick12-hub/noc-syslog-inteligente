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
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row          # permite row["columna"]
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite las trae apagadas por defecto
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


def init_db(conn: sqlite3.Connection):
    """Crea las tablas (si no existen) y carga/actualiza el catálogo de severidades."""
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
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
