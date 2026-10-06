"""
Datos SIMULADOS para pruebas y demostración.

Todas las IP pertenecen a los rangos reservados para documentación por la
RFC 5737 (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24): no existen en
Internet ni corresponden a ninguna red de producción. La única excepción es
SIM-GEN-LOCAL (127.0.0.1, loopback): representa al simulador que corre en este
mismo PC y nunca sale a la red.
Todos los nombres empiezan por "SIM-" y llevan is_simulated = 1.
"""
from .db import audit, now_iso

SIMULATED_DEVICES = [
    # nombre,          ip,              marca,      modelo,          versión,          ubicación,              estado,   autorizado
    ("SIM-CORE-RTR01", "192.0.2.1",     "Cisco",    "ISR 4331",      "IOS-XE 17.9.4",  "Sede Bogotá - Rack A",  "activo", 1),
    ("SIM-DIST-SW01",  "192.0.2.10",    "Cisco",    "Catalyst 9300", "IOS-XE 17.9.4",  "Sede Bogotá - Piso 2",  "activo", 1),
    ("SIM-EDGE-FW01",  "198.51.100.1",  "Fortinet", "FortiGate 60F", "FortiOS 7.4.3",  "Sede Bogotá - DMZ",     "alerta", 1),
    ("SIM-BR-RTR02",   "198.51.100.20", "Huawei",   "AR6120",        "VRP V300R022",   "Sede Medellín",         "activo", 1),
    ("SIM-BR-SW02",    "203.0.113.5",   "Huawei",   "S5735-L",       "VRP V200R022",   "Sede Cali",             "caido",  1),
    ("SIM-LAB-AP01",   "203.0.113.99",  "Otro",     "AP genérico",   "1.0",            "Laboratorio",           "desconocido", 0),
    # Fase 2: el simulador envía UDP desde este mismo PC (127.0.0.1, loopback).
    # Se registra como fuente autorizada para que esos eventos de prueba se acepten.
    ("SIM-GEN-LOCAL",  "127.0.0.1",     "Otro",     "Simulador",     "scripts/simulador.py", "Este PC - generador de pruebas", "activo", 1),
]


def seed_devices(conn) -> int:
    """Inserta los equipos simulados que aún no existan. Devuelve cuántos insertó."""
    inserted = 0
    for name, ip, vendor, model, version, location, status, authorized in SIMULATED_DEVICES:
        exists = conn.execute("SELECT 1 FROM devices WHERE name = ?", (name,)).fetchone()
        if exists:
            continue
        ts = now_iso()
        conn.execute(
            "INSERT INTO devices (name, ip, vendor, model, version, location, status, "
            "authorized, is_simulated, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (name, ip, vendor, model, version, location, status, authorized, ts, ts),
        )
        inserted += 1
    conn.commit()
    if inserted:
        audit(conn, "sistema", "seed.devices", "devices", None,
              f"{inserted} equipos SIMULADOS cargados")
    return inserted
