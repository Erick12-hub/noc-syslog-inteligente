"""Pruebas del parser Syslog (RF-03: facility y severidad a partir del PRI)."""
import pytest

from app.syslog_parser import parse


@pytest.mark.parametrize("pri, facility, severity", [
    (0, 0, 0),       # kern.emerg
    (13, 1, 5),      # user.notice
    (34, 4, 2),      # auth.crit (ejemplo de la RFC 5424)
    (187, 23, 3),    # local7.err  (Cisco)
    (191, 23, 7),    # máximo válido
])
def test_pri_calcula_facility_y_severidad(pri, facility, severity):
    p = parse(f"<{pri}>Oct  5 18:00:00 host app: prueba")
    assert p["facility"] == facility
    assert p["severity"] == severity


def test_cisco_ios():
    p = parse("<187>45: *Oct  5 10:15:42.551: SIM-CORE-RTR01 %LINK-3-UPDOWN: "
              "Interface GigabitEthernet0/0/2, changed state to down")
    assert p["format"] == "rfc3164"
    assert p["vendor_hint"] == "Cisco"
    assert p["mnemonic"] == "LINK-3-UPDOWN"
    assert p["hostname"] == "SIM-CORE-RTR01"
    assert p["severity"] == 3 and p["severity_name"] == "Error"
    assert p["facility_name"] == "local7"
    assert p["message"].startswith("Interface GigabitEthernet0/0/2")


def test_huawei_vrp():
    p = parse("<186>Oct 5 2026 13:05:10 SIM-BR-RTR02 %%01IFNET/2/LINK_STATE(l)[1]: "
              "The interface GigabitEthernet0/0/1 changed to DOWN.")
    assert p["vendor_hint"] == "Huawei"
    assert p["mnemonic"] == "IFNET/2/LINK_STATE"
    assert p["hostname"] == "SIM-BR-RTR02"
    assert p["severity"] == 2


def test_fortinet_clave_valor():
    p = parse('<185>date=2026-10-05 time=23:50:31 devname="SIM-EDGE-FW01" logid="0100032002" '
              'type="event" subtype="system" level="alert" msg="Administrator admin login failed"')
    assert p["vendor_hint"] == "Fortinet"
    assert p["format"] == "clave_valor"
    assert p["hostname"] == "SIM-EDGE-FW01"
    assert p["severity"] == 1
    assert p["message"] == "Administrator admin login failed"
    assert p["event_time"] == "2026-10-05 23:50:31"


def test_rfc5424():
    p = parse("<34>1 2026-10-05T22:14:15.003Z mymachine su - ID47 - 'su root' failed")
    assert p["format"] == "rfc5424"
    assert p["hostname"] == "mymachine"
    assert p["app_name"] == "su"
    assert p["facility_name"] == "auth" and p["severity"] == 2


def test_sin_pri_asume_informational():
    p = parse("texto sin cabecera")
    assert p["severity"] == 6
    assert "sin_pri" in p["parse_flags"]


def test_pri_fuera_de_rango_no_se_acepta():
    p = parse("<999>mensaje")
    assert p["pri"] is None
    assert "sin_pri" in p["parse_flags"]


def test_severidad_inconsistente_se_marca():
    # PRI dice severidad 1 pero la firma Cisco dice 5
    p = parse("<185>1: *Oct  5 23:59:01.000: R1 %BGP-5-ADJCHANGE: neighbor down")
    assert "severidad_inconsistente" in p["parse_flags"]


def test_caracteres_de_control_se_eliminan():
    p = parse("<13>Oct  5 18:00:00 host app: linea1\nlinea2\x1b[31m\x00")
    assert "\n" not in p["message"] and "\x1b" not in p["message"] and "\x00" not in p["message"]


def test_mensaje_muy_largo_se_recorta():
    p = parse("<13>" + "A" * 5000)
    assert len(p["message"]) < 2100
    assert "mensaje_recortado" in p["parse_flags"]
