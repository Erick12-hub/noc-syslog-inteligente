"""
NOC Syslog Inteligente - fábrica de la aplicación Flask.

create_app() arma la aplicación: carga la configuración, prepara la base de
datos y registra los módulos (blueprints):
    devices   -> /api/devices     inventario
    events    -> /api/events      eventos Syslog
    incidents -> /api/incidents   incidentes
    dashboard -> /api/dashboard   resumen para el dashboard
    configgen -> /api/config      generador de configuraciones Syslog (Fase 4)
    console   -> /api/console     consola simulada de solo lectura (Fase 4)
    proposals -> /api/proposals   propuestas de acción con aprobación humana (Fase 4)
    audit     -> /api/audit       consulta de la auditoría (Fase 4)
    views     -> páginas web
    auth      -> /login, /logout, /api/auth/me  (Fase 8: sesión, roles y CSRF)
    admin_api -> /api/admin    usuarios y resumen de seguridad (Fase 8.3, solo admin)
    interfaces -> /api/devices/<id>/interfaces  interfaces de cada equipo (Fase 8.4)
    connector -> /api/devices/<id>/session   conexión con los equipos y trazabilidad (Fase 9.1)
    diagnostics -> /api/devices/<id>/diagnostic  ping y traceroute desde el equipo (Fase 9.4)
    consistency -> /api/consistency   reloj (NTP), consistencia y cadena de auditoría (Fase 9.5)
"""
from flask import Flask, jsonify

from .config import Config
from . import db

APP_VERSION = "0.4.0"


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Crea/actualiza las tablas al arrancar. init_db es idempotente: si ya
    # existen no borra nada; solo aplica las migraciones pendientes.
    conn = db.connect(app.config["DATABASE_PATH"])
    db.init_db(conn)
    conn.close()

    # Cerrar la conexión SQLite al final de cada petición
    app.teardown_appcontext(db.close_db)

    # Registrar módulos
    from . import (admin_api, audit_api, auth, configgen, connector, consistency, console, dashboard,
                   devices, diagnostics, events, incidents, interfaces, proposals, views)
    for module in (auth, devices, interfaces, connector, diagnostics, consistency, events, incidents,
                   dashboard, configgen, console, proposals, audit_api, admin_api, views):
        app.register_blueprint(module.bp)

    # Fase 8: cada petición pasa por el control de sesión, CSRF y roles
    auth.init_app(app)

    # Variables disponibles en todas las plantillas HTML
    @app.context_processor
    def inject_version():
        return {"app_version": APP_VERSION}

    @app.get("/api/health")
    def health():
        """Chequeo de salud: versión y número de tablas en la base de datos."""
        conn = db.get_db()
        tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        return jsonify(status="ok", version=APP_VERSION, tables=tables)

    @app.errorhandler(413)
    def too_large(_e):
        return jsonify(errors=["El archivo supera el máximo permitido (2 MB)"]), 413

    return app
