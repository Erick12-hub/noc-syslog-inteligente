"""
Páginas web (HTML). La lógica vive en la API; las páginas solo la consumen
con JavaScript (fetch) y muestran los datos.
"""
from flask import Blueprint, render_template

bp = Blueprint("views", __name__)


@bp.get("/")
def dashboard():
    return render_template("dashboard.html", active="dashboard")


@bp.get("/inventario")
def inventario():
    return render_template("inventario.html", active="inventario")


@bp.get("/eventos")
def eventos():
    return render_template("eventos.html", active="eventos")


@bp.get("/incidentes")
def incidentes():
    return render_template("incidentes.html", active="incidentes")


@bp.get("/configuraciones")
def configuraciones():
    return render_template("configuraciones.html", active="configuraciones")


@bp.get("/cambios")
def cambios():
    """Fase 10.2: solicitudes de cambio con matriz de riesgo y rollback."""
    return render_template("cambios.html", active="cambios")


@bp.get("/consola")
def consola():
    return render_template("consola.html", active="consola")


@bp.get("/auditoria")
def auditoria():
    return render_template("auditoria.html", active="auditoria")


@bp.get("/seguridad")
def seguridad():
    """Fase 8.3: ventana de administración de seguridad (solo admin_seguridad)."""
    return render_template("seguridad.html", active="seguridad")
