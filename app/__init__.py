"""
NOC Syslog Inteligente - fábrica de la aplicación Flask.

En la Fase 1 solo expone /api/health para verificar que Flask arranca y que
la base de datos responde. Los módulos (inventario, eventos, incidentes...)
se registran en las fases siguientes.
"""
from flask import Flask, jsonify

from .config import Config
from . import db

APP_VERSION = "0.1.0-dev"


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Cerrar la conexión SQLite al final de cada petición
    app.teardown_appcontext(db.close_db)

    @app.get("/api/health")
    def health():
        """Chequeo de salud: versión y número de tablas en la base de datos."""
        conn = db.get_db()
        tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        return jsonify(status="ok", version=APP_VERSION, tables=tables)

    return app
