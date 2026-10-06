"""
Páginas web (HTML). La lógica vive en la API; las páginas solo la consumen
con JavaScript (fetch) y muestran los datos.
"""
from flask import Blueprint, redirect, render_template, url_for

bp = Blueprint("views", __name__)


@bp.get("/")
def home():
    # En la Fase 3 la página de inicio será el dashboard
    return redirect(url_for("views.inventario"))


@bp.get("/inventario")
def inventario():
    return render_template("inventario.html", active="inventario")


@bp.get("/eventos")
def eventos():
    return render_template("eventos.html", active="eventos")
