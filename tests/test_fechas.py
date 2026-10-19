"""
Pruebas de la Fase 7 (paso 7.2): filtro de fecha hasta HOY en hora de Colombia
y marca 'fecha_futura' en eventos con reloj adelantado.

Las horas "ahora" se fijan a mano (parámetro now) para que las pruebas den el
mismo resultado cualquier día y a cualquier hora en que se ejecuten.
"""
from datetime import date, datetime, timedelta, timezone

from app.ingest import ingest
from app.timeutil import (event_time_to_utc, is_future, local_day_bounds_utc,
                          local_today, validate_date_range)

UTC = timezone.utc
# 16-oct-2026 a las 9:30 p. m. en Bogotá = 17-oct-2026 02:30 UTC
NOCHE_BOGOTA = datetime(2026, 10, 17, 2, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# 1. "Hoy" y límites del día en hora de Colombia
# ---------------------------------------------------------------------------
def test_hoy_es_la_fecha_de_colombia_no_la_de_utc():
    # En UTC ya es el 17, pero en Colombia todavía es el 16
    assert local_today(NOCHE_BOGOTA) == date(2026, 10, 16)


def test_limites_de_un_dia_de_colombia_en_utc():
    assert local_day_bounds_utc(date(2026, 10, 16)) == ("2026-10-16T05:00:00Z", "2026-10-17T04:59:59Z")


# ---------------------------------------------------------------------------
# 2. Validación del rango del filtro
# ---------------------------------------------------------------------------
def test_rango_valido_hasta_hoy():
    errors, bounds = validate_date_range("2026-10-01", "2026-10-16", now=NOCHE_BOGOTA)
    assert errors == []
    assert bounds == {"desde_utc": "2026-10-01T05:00:00Z", "hasta_utc": "2026-10-17T04:59:59Z"}


def test_fecha_futura_en_el_filtro_se_rechaza():
    errors, _ = validate_date_range(None, "2026-10-17", now=NOCHE_BOGOTA)
    assert len(errors) == 1 and "posterior a hoy (2026-10-16" in errors[0]


def test_formato_invalido_y_fecha_imposible():
    errors, _ = validate_date_range("16/10/2026", "2026-02-30", now=NOCHE_BOGOTA)
    assert len(errors) == 2 and all("AAAA-MM-DD" in e for e in errors)


def test_desde_posterior_a_hasta():
    errors, _ = validate_date_range("2026-10-10", "2026-10-05", now=NOCHE_BOGOTA)
    assert errors == ["La fecha 'desde' no puede ser posterior a 'hasta'"]


# ---------------------------------------------------------------------------
# 3. API: el servidor valida aunque la interfaz no lo haga
# ---------------------------------------------------------------------------
def test_api_rechaza_fecha_futura_con_400(client):
    manana = (local_today() + timedelta(days=1)).isoformat()
    r = client.get(f"/api/events?hasta={manana}")
    assert r.status_code == 400 and "posterior a hoy" in r.json["errors"][0]


def test_api_acepta_hoy_y_encuentra_eventos_de_hoy(client, conn):
    ingest(conn, "<189>1: *Oct  5 08:00:01.112: SIM-CORE-RTR01 %SYS-5-RESTART: System restarted",
           "192.0.2.1", "simulador")
    hoy = local_today().isoformat()
    r = client.get(f"/api/events?desde={hoy}&hasta={hoy}")
    assert r.status_code == 200 and len(r.json) == 1


def test_api_entrega_la_fecha_de_hoy(client):
    r = client.get("/api/events/today")
    assert r.status_code == 200 and r.json["today"] == local_today().isoformat()


# ---------------------------------------------------------------------------
# 4. Fecha que trae el mensaje -> UTC
# ---------------------------------------------------------------------------
def test_fecha_rfc5424_respeta_su_zona():
    assert event_time_to_utc("2026-10-16T10:00:00-05:00") == datetime(2026, 10, 16, 15, 0, tzinfo=UTC)


def test_fecha_fortinet_se_toma_como_hora_de_colombia():
    assert event_time_to_utc("2026-10-05 08:00:00") == datetime(2026, 10, 5, 13, 0, tzinfo=UTC)


def test_fecha_huawei_con_anio():
    assert event_time_to_utc("Oct 5 2026 13:05:10") == datetime(2026, 10, 5, 18, 5, 10, tzinfo=UTC)


def test_fecha_cisco_sin_anio_usa_el_anio_actual():
    assert event_time_to_utc("Oct 5 10:15:42.551", now=NOCHE_BOGOTA) == \
        datetime(2026, 10, 5, 15, 15, 42, tzinfo=UTC)


def test_cambio_de_anio_31_dic_recibido_el_1_ene():
    # Mensaje sin año del 31-dic que llega el 1-ene: pertenece al año ANTERIOR.
    # Ojo: 31-dic-2026 23:59:58 en Bogotá = 1-ene-2027 04:59:58 en UTC, por eso
    # se compara la fecha completa y no solo el año.
    primero_enero = datetime(2027, 1, 1, 5, 30, tzinfo=UTC)
    assert event_time_to_utc("Dec 31 23:59:58", now=primero_enero) == \
        datetime(2027, 1, 1, 4, 59, 58, tzinfo=UTC)          # y NO 1-ene-2028


def test_fecha_ilegible_no_rompe_nada():
    assert event_time_to_utc("ayer en la tarde") is None
    assert event_time_to_utc("Feb 30 10:00:00", now=NOCHE_BOGOTA) is None


# ---------------------------------------------------------------------------
# 5. Marca 'fecha_futura' (reloj del equipo adelantado)
# ---------------------------------------------------------------------------
def test_tolerancia_de_latencia():
    recibido = NOCHE_BOGOTA
    assert not is_future(recibido + timedelta(seconds=60), recibido, tolerance_s=120)
    assert is_future(recibido + timedelta(minutes=10), recibido, tolerance_s=120)


def test_evento_con_reloj_adelantado_se_guarda_y_se_marca(conn):
    r = ingest(conn, "<187>1 2099-01-01T00:00:00Z SIM-CORE-RTR01 IOS - - - "
                     "%LINK-3-UPDOWN: Interface Gi0/1, changed state to down", "192.0.2.1", "simulador")
    assert r["id"] is not None                       # NO se rechaza: es evidencia
    row = conn.execute("SELECT flags, event_time_utc FROM syslog_events WHERE id = ?",
                       (r["id"],)).fetchone()
    assert "fecha_futura" in row["flags"] and row["event_time_utc"] == "2099-01-01T00:00:00Z"


def test_evento_con_fecha_pasada_no_se_marca(conn):
    r = ingest(conn, '<189>date=2026-10-05 time=09:30:12 devname="SIM-EDGE-FW01" logid="0100044547" '
                     'type="event" level="notice" msg="Edit firewall.policy 12"', "198.51.100.1", "simulador")
    row = conn.execute("SELECT flags, event_time_utc FROM syslog_events WHERE id = ?",
                       (r["id"],)).fetchone()
    assert "fecha_futura" not in (row["flags"] or "")
    assert row["event_time_utc"] == "2026-10-05T14:30:12Z"


def test_filtrar_eventos_con_fecha_futura(client, conn):
    ingest(conn, "<187>1 2099-01-01T00:00:00Z SIM-CORE-RTR01 IOS - - - prueba de reloj", "192.0.2.1", "simulador")
    r = client.get("/api/events?flag=fecha_futura")
    assert r.status_code == 200 and len(r.json) == 1
