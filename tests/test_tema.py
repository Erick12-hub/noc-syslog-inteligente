"""Pruebas del selector de tema claro/oscuro (Fase 7)."""


def test_todas_las_paginas_tienen_el_selector_de_tema(client):
    for page in ("/", "/inventario", "/eventos", "/incidentes", "/configuraciones", "/consola", "/auditoria"):
        html = client.get(page).get_data(as_text=True)
        assert 'id="theme-toggle"' in html and "theme.js" in html, page


def test_el_script_de_tema_se_sirve(client):
    r = client.get("/static/theme.js")
    assert r.status_code == 200 and "localStorage" in r.get_data(as_text=True)
    r.close()


def test_la_hoja_de_estilos_define_el_tema_claro(client):
    r = client.get("/static/styles.css")
    css = r.get_data(as_text=True)
    r.close()
    assert ':root[data-theme="light"]' in css and "color-scheme: light" in css
