# Reporte de pruebas - NOC Syslog Inteligente

> Generado por `python scripts/reporte_pruebas.py`. Cada prueba usa una base de datos TEMPORAL, datos SIMULADOS y ninguna conexión real (equipos ni Telegram).

- Fecha: 2026-10-26 14:34  ·  versión del NOC: 0.5.0
- Equipo: Windows 11  ·  Python 3.14.7
- Resultado de pytest: `623 passed in 164.01s (0:02:44)`

**623 de 623 pruebas superadas (100.0 %), 0 fallidas, en 161.7 s.**

## Resumen por categoría

| Categoría | Archivos | Pruebas | Superadas | Fallidas |
|---|---:|---:|---:|---:|
| Funcionales | 8 | 144 | 144 | 0 |
| Seguridad | 5 | 142 | 142 | 0 |
| Integridad | 3 | 67 | 67 | 0 |
| Cambios | 3 | 119 | 119 | 0 |
| Operación | 5 | 132 | 132 | 0 |
| Rendimiento | 2 | 19 | 19 | 0 |
| **Total** | **26** | **623** | **623** | **0** |

## Funcionales

| Archivo | Qué valida | Pruebas | Resultado |
|---|---|---:|---|
| `tests/test_api.py` | API de eventos, equipos e importación | 10 | Superadas |
| `tests/test_fechas.py` | Filtros de fecha en hora de Colombia | 19 | Superadas |
| `tests/test_incidents.py` | Incidentes, correlación y tablero | 16 | Superadas |
| `tests/test_ingest.py` | Ingesta, deduplicación e importación de archivos | 7 | Superadas |
| `tests/test_interfaces_equipo.py` | Interfaces del inventario por equipo | 39 | Superadas |
| `tests/test_interfaz_puertos.py` | Interfaz y puertos en los eventos | 36 | Superadas |
| `tests/test_parser.py` | Lectura de Syslog RFC 3164/5424, Cisco, FortiGate y Huawei | 14 | Superadas |
| `tests/test_tema.py` | Tema claro/oscuro de la interfaz | 3 | Superadas |

## Seguridad

| Archivo | Qué valida | Pruebas | Resultado |
|---|---|---:|---|
| `tests/test_admin_seguridad.py` | Administración de usuarios y seguridad | 15 | Superadas |
| `tests/test_auth.py` | Inicio de sesión, bloqueo, CSRF, roles y sesión | 44 | Superadas |
| `tests/test_seguridad.py` | Generador de configuraciones, consola segura e inyección a la IA | 29 | Superadas |
| `tests/test_telegram_ia.py` | Avisos por Telegram y defensa del asistente de IA | 32 | Superadas |
| `tests/test_validacion.py` | Validación estricta de parámetros | 22 | Superadas |

## Integridad

| Archivo | Qué valida | Pruebas | Resultado |
|---|---|---:|---|
| `tests/test_auditoria_cadena.py` | Auditoría encadenada con SHA-256 | 14 | Superadas |
| `tests/test_consistencia.py` | Reloj NTP, consistencia y cadena automática | 33 | Superadas |
| `tests/test_respaldos.py` | Respaldo, verificación y restauración de la base | 20 | Superadas |

## Cambios

| Archivo | Qué valida | Pruebas | Resultado |
|---|---|---:|---|
| `tests/test_cambios.py` | Solicitudes de cambio, matriz de riesgo y ventana | 54 | Superadas |
| `tests/test_ejecucion_cambios.py` | Aprobación, ejecución, verificación y rollback | 27 | Superadas |
| `tests/test_versiones_config.py` | Versiones de configuración, ocultar secretos y diferencias | 38 | Superadas |

## Operación

| Archivo | Qué valida | Pruebas | Resultado |
|---|---|---:|---|
| `tests/test_conexiones.py` | Conexión con equipos (consola/SSH) y trazabilidad | 30 | Superadas |
| `tests/test_configuracion_base.py` | Configuración base para el laboratorio | 37 | Superadas |
| `tests/test_diagnostico.py` | Ping y traceroute desde el equipo | 27 | Superadas |
| `tests/test_interfaces_reales.py` | Interfaces reales leídas del equipo | 20 | Superadas |
| `tests/test_metricas.py` | MTTA, MTTR, SLA e indicadores de cambios | 18 | Superadas |

## Rendimiento

| Archivo | Qué valida | Pruebas | Resultado |
|---|---|---:|---|
| `tests/test_carga.py` | Prueba de carga reducida y control de tormentas | 7 | Superadas |
| `tests/test_optimizacion.py` | Índices, consultas y límites de la base | 12 | Superadas |
