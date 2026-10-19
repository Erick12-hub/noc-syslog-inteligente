"""
Pruebas de la Fase 7 (paso 7.3): los parámetros inválidos ya no se ignoran y se
valida la coherencia entre el equipo del inventario y la marca del mensaje.
Todos los datos son SIMULADOS (IP de documentación RFC 5737).
"""
import io

import pytest

from app.ingest import check_import_vendor, ingest

CISCO_LOG = ("<187>1: *Oct  5 10:15:42.551: SIM-CORE-RTR01 %LINK-3-UPDOWN: Interface Gi0/1, changed state to down\n"
             "<189>2: *Oct  5 10:16:00.000: SIM-CORE-RTR01 %SYS-5-CONFIG_I: Configured from console by noc_admin\n")
FORTI_LINE = ('<189>date=2026-10-05 time=09:30:12 devname="SIM-EDGE-FW01" logid="0100044547" '
              'type="event" level="notice" msg="Edit firewall.policy 12"')


def _devices(client):
    return {d["name"]: d for d in client.get("/api/devices").json}


# ---------------------------------------------------------------------------
# 1. Filtros de eventos: cada valor inválido produce su propio mensaje
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query, texto", [
    ("severity=9", "Severidad: 9 está fuera de rango"),
    ("sev_max=-1", "Severidad máxima: -1 está fuera de rango"),
    ("severity=alta", "no es un número entero"),
    ("vendor=Juniper", "Marca: valor no válido"),
    ("flag=borrar_todo", "Marca de seguridad: valor no válido"),
    ("limit=0", "Límite: 0 está fuera de rango"),
    ("limit=501", "Límite: 501 está fuera de rango"),
    ("device_id=999", "no existe en el inventario"),
])
def test_filtro_de_eventos_invalido(client, query, texto):
    r = client.get(f"/api/events?{query}")
    assert r.status_code == 400 and texto in " ".join(r.json["errors"])


def test_se_informan_todos_los_errores_a_la_vez(client):
    r = client.get("/api/events?severity=9&vendor=Juniper&port=0&hasta=2999-01-01")
    assert r.status_code == 400 and len(r.json["errors"]) == 4


def test_filtros_validos_siguen_funcionando(client):
    r = client.get("/api/events?vendor=Cisco&severity=3&sev_max=4&flag=fecha_futura&limit=500")
    assert r.status_code == 200


def test_parametro_vacio_equivale_a_no_enviarlo(client):
    # La interfaz web nunca envía vacíos, pero un enlace escrito a mano sí podría
    assert client.get("/api/events?vendor=&severity=").status_code == 200


# ---------------------------------------------------------------------------
# 2. Otros listados
# ---------------------------------------------------------------------------
def test_estado_de_incidentes_invalido(client):
    assert client.get("/api/incidents?estado=borrados").status_code == 400
    assert client.get("/api/incidents?estado=cerrado").status_code == 200


def test_auditoria_parametros_invalidos(client):
    r = client.get("/api/audit?result=perdonado&limit=5000")
    assert r.status_code == 400 and len(r.json["errors"]) == 2
    assert client.get("/api/audit?result=bloqueado&limit=50").status_code == 200


def test_consola_marca_invalida(client):
    assert client.get("/api/console/allowed?vendor=Juniper").status_code == 400


# ---------------------------------------------------------------------------
# 3. Coherencia equipo - marca
# ---------------------------------------------------------------------------
def test_detectar_archivo_de_otra_marca():
    problem = check_import_vendor(CISCO_LOG.splitlines(), "Fortinet")
    assert problem and "parece de Cisco" in problem and "es Fortinet" in problem


def test_archivo_de_la_marca_correcta_pasa():
    assert check_import_vendor(CISCO_LOG.splitlines(), "Cisco") is None


def test_archivo_sin_lineas_reconocibles_no_se_juzga():
    assert check_import_vendor(["texto libre sin formato", "# comentario"], "Huawei") is None


def test_importar_log_cisco_en_fortigate_se_rechaza_y_audita(client, conn):
    fw = _devices(client)["SIM-EDGE-FW01"]
    r = client.post("/api/events/import", data={"device_id": fw["id"],
                                                "file": (io.BytesIO(CISCO_LOG.encode()), "cisco.log")},
                    content_type="multipart/form-data")
    assert r.status_code == 409 and "parece de Cisco" in r.json["errors"][0]
    # No se guardó NINGÚN evento y quedó registro en auditoría
    assert conn.execute("SELECT COUNT(*) FROM syslog_events").fetchone()[0] == 0
    row = conn.execute("SELECT result FROM audit_log WHERE action = 'syslog.import_rechazado'").fetchone()
    assert row["result"] == "bloqueado"


def test_mensaje_suelto_de_otra_marca_se_marca(conn):
    # La IP 198.51.100.1 es el FortiGate, pero el mensaje tiene formato Cisco:
    # posible suplantación de la fuente. Se guarda (evidencia) y se marca.
    r = ingest(conn, CISCO_LOG.splitlines()[0], "198.51.100.1", "simulador")
    assert "marca_inconsistente" in r["flags"]
    # El incidente no repite el contenido no confiable ("LINK-3-UPDOWN")
    inc = conn.execute("SELECT title FROM incidents WHERE id = ?", (r["incident"]["id"],)).fetchone()
    assert inc["title"] == "Marca inconsistente: posible suplantación de SIM-EDGE-FW01"
    row = conn.execute("SELECT result FROM audit_log WHERE action = 'syslog.sospechoso'").fetchone()
    assert row["result"] == "alerta"


def test_mensaje_de_la_marca_correcta_no_se_marca(conn):
    r = ingest(conn, FORTI_LINE, "198.51.100.1", "simulador")
    assert "marca_inconsistente" not in r["flags"]


def test_configuracion_de_otra_marca_para_un_equipo_se_rechaza(client):
    fw = _devices(client)["SIM-EDGE-FW01"]
    r = client.get(f"/api/config/generate?vendor=Cisco&device_id={fw['id']}&server_ip=192.0.2.250"
                   "&ntp=192.0.2.123&port=5514&severity=6&source=GigabitEthernet0/0/0")
    assert r.status_code == 400 and "es Fortinet" in r.json["errors"][0]


def test_configuracion_para_equipo_inexistente_se_rechaza(client):
    r = client.get("/api/config/generate?vendor=Cisco&device_id=999&server_ip=192.0.2.250"
                   "&ntp=192.0.2.123&port=5514&severity=6&source=GigabitEthernet0/0/0")
    assert r.status_code == 400 and "no existe" in r.json["errors"][0]
