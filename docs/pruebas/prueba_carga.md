# Prueba de carga - NOC Syslog Inteligente

> Generado por `python scripts/prueba_carga.py --reporte`. **Todos los datos son SIMULADOS (SIM)**; se usó una base temporal y ningún aviso salió por Telegram.

- Fecha: 2026-10-26 14:29  ·  versión del NOC: 0.5.0
- Equipo de pruebas: Windows 11  ·  Python 3.14.7

## 1. Ingesta (mismo camino que el receptor)

| Mensajes | Tiempo | Mensajes/s | p50 | p95 | p99 | Máx. | Incidentes | Errores |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2000 | 4.82 s | 415 | 2.27 ms | 3.04 ms | 3.62 ms | 24.76 ms | 14 | 0 |

## 2. Concurrencia (varios procesos escribiendo a la vez)

| Hilos | Mensajes | Mensajes/s | Errores (bloqueos) | Cadena de auditoría |
|---:|---:|---:|---:|---|
| 4 | 1000 | 408 | 0 | ÍNTEGRA (14 registros) |

## 3. Control de tormentas

| Límite por minuto | Enviados | Aceptados | Descartados | Resultado |
|---:|---:|---:|---:|---|
| 100 | 150 | 100 | 50 | Correcto |

## 4. Consultas de la web con la base cargada

| Consulta | p50 | p95 | Respuesta HTTP |
|---|---:|---:|---|
| Eventos (página 1) (`/api/events?limit=50`) | 24.1 ms | 25.9 ms | 200 |
| Incidentes (`/api/incidents`) | 19.4 ms | 21.2 ms | 200 |
| Tablero (`/api/dashboard`) | 21.7 ms | 23.4 ms | 200 |
| Indicadores 30 días (`/api/metrics?dias=30`) | 18.2 ms | 23.9 ms | 200 |

## Conclusión

Prueba SUPERADA: el NOC procesó 415 mensajes/s en un solo proceso (p95 3.0 ms por mensaje), 4 escritores simultáneos sin bloqueos y con la auditoría íntegra, el control de tormentas aceptó 100 de 150 (límite 100) y las consultas de la web respondieron con p95 ≤ 26 ms.

Límites de la prueba: se ejecuta en un solo PC (sin red real entre equipos) y con la base SQLite local; mide la capacidad del procesamiento, no la de una red de producción.
