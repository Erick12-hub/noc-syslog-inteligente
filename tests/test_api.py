"""Pruebas funcionales de la API: inventario (RF-01) y eventos (RF-02, RF-06)."""
import io

NEW_DEVICE = {"name": "SIM-TEST-SW09", "ip": "192.0.2.99", "vendor": "Huawei",
              "model": "S5735", "version": "V200", "location": "Lab", "status": "activo"}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json["status"] == "ok" and r.json["tables"] == 7


def test_listar_equipos_simulados(client):
    r = client.get("/api/devices")
    assert r.status_code == 200
    assert len(r.json) == 7
    assert all(d["is_simulated"] == 1 for d in r.json)


def test_crud_completo_de_equipo(client):
    # Crear
    r = client.post("/api/devices", json=NEW_DEVICE)
    assert r.status_code == 201
    dev = r.json
    assert dev["name"] == "SIM-TEST-SW09" and dev["authorized"] == 1
    # Editar (cambia solo el estado; la fecha de actualización se registra)
    r = client.put(f"/api/devices/{dev['id']}", json={"status": "mantenimiento"})
    assert r.status_code == 200 and r.json["status"] == "mantenimiento"
    assert r.json["updated_at"] >= dev["updated_at"]
    # Eliminar
    assert client.delete(f"/api/devices/{dev['id']}").status_code == 200
    assert client.get(f"/api/devices/{dev['id']}").status_code == 404


def test_validaciones_de_equipo(client):
    bad = dict(NEW_DEVICE, ip="999.1.1.1", vendor="Juniper", name="con espacios")
    r = client.post("/api/devices", json=bad)
    assert r.status_code == 400
    text = " ".join(r.json["errors"])
    assert "IP inválida" in text and "Marca inválida" in text and "Nombre inválido" in text


def test_campos_obligatorios(client):
    r = client.post("/api/devices", json={})
    assert r.status_code == 400 and len(r.json["errors"]) == 3


def test_no_se_permiten_duplicados(client):
    r = client.post("/api/devices", json=dict(NEW_DEVICE, ip="192.0.2.1"))  # IP de SIM-CORE-RTR01
    assert r.status_code == 409


def test_acciones_quedan_en_auditoria(client, conn):
    client.post("/api/devices", json=NEW_DEVICE)
    row = conn.execute("SELECT * FROM audit_log WHERE action = 'device.create'").fetchone()
    assert row["actor"] == "tester" and "SIM-TEST-SW09" in row["detail"]


def test_importar_y_filtrar_eventos(client):
    devices = {d["name"]: d["id"] for d in client.get("/api/devices").json}
    log = (b"<187>1: *Oct  5 10:15:42.551: SIM-CORE-RTR01 %LINK-3-UPDOWN: Interface Gi0/0/2, changed state to down\n"
           b"<189>2: *Oct  5 10:16:00.000: SIM-CORE-RTR01 %SYS-5-CONFIG_I: Configured from console by noc_admin\n")
    r = client.post("/api/events/import", data={"device_id": devices["SIM-CORE-RTR01"],
                                                "file": (io.BytesIO(log), "cisco.log")},
                    content_type="multipart/form-data")
    assert r.status_code == 200 and r.json["nuevas"] == 2

    # Filtro por severidad (solo el Error)
    r = client.get("/api/events?severity=3")
    assert len(r.json) == 1 and r.json[0]["mnemonic"] == "LINK-3-UPDOWN"
    # Filtro por marca y equipo combinados
    r = client.get(f"/api/events?vendor=Cisco&device_id={devices['SIM-CORE-RTR01']}")
    assert len(r.json) == 2
    # Filtro sin resultados
    assert client.get("/api/events?vendor=Huawei").json == []


def test_filtros_invalidos_se_ignoran(client):
    r = client.get("/api/events?severity=99&limit=abc&device_id=x")
    assert r.status_code == 200


def test_paginas_web_cargan(client):
    for url in ("/inventario", "/eventos"):
        r = client.get(url)
        assert r.status_code == 200 and b"DATOS SIMULADOS" in r.data
