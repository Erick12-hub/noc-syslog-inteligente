# Registro de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
[versionado semántico](https://semver.org/lang/es/). Todos los datos son **SIMULADOS**.

## [0.2.1] - 2026-10-17 — Mejoras del Corte 2 (Fase 7)

Primera versión del Corte 3: corrige los hallazgos de la revisión del MVP antes de
conectar equipos reales. 168 pruebas automáticas (76 en v0.2.0).

### Agregado
- Interfaz y puertos de origen/destino en cada evento (Cisco, Huawei, Fortinet), con filtros validados.
- Fechas de asignación e inicio en incidentes (`assigned_at`, `started_at`), base de MTTA/MTTR.
- Marca `fecha_futura` en eventos con reloj adelantado y fecha del mensaje en UTC (`event_time_utc`), base del monitoreo NTP.
- Marca `marca_inconsistente` cuando el formato del mensaje no coincide con la marca del inventario (posible suplantación).
- Paginación del listado de eventos (100 por página, total en encabezados `X-Total-Count`).
- Selector de tema claro y oscuro.
- Servidor de operación `serve.py` (waitress, sin depuración).
- Escenarios del simulador: `reloj_desfasado` y `suplantacion`.

### Cambiado
- El filtro de fechas trabaja en hora de Colombia (UTC-5) y no admite fechas posteriores a hoy (validado en interfaz y servidor).
- Los parámetros inválidos de la API responden **400 con la lista de errores** en lugar de ignorarse.
- Importar un archivo de otra marca que la del equipo se rechaza antes de guardar nada (409) y queda auditado.
- `run.py` ya no fija `debug=True`: la depuración solo se activa con `FLASK_DEBUG=1`.
- SQLite en modo WAL con `busy_timeout` e índices compuestos (deduplicación, equipo+fecha, severidad+fecha, correlación).
- GitHub Actions: `actions/checkout@v5` y `actions/setup-python@v6` (Node.js 24).

### Corregido
- Eventos de Bogotá después de las 7 p. m. quedaban en el día siguiente al filtrar por fecha (se comparaba en UTC).
- Generar configuración para un equipo inexistente o de otra marca producía una configuración genérica sin aviso.

### Seguridad
- El título de un incidente por marca inconsistente no repite el contenido del mensaje (dato no confiable).
- Puertos fuera de 1–65535 e interfaces con caracteres extraños se descartan y se marcan.

## [0.2.0] - 2026-10-10 — MVP (Corte 2)

### Agregado
- Dashboard con indicadores de 24 h, equipos por estado, eventos por severidad y por hora (Fase 3).
- Incidentes automáticos (severidad 0–3 de fuente autorizada) con correlación por equipo y código (Fase 3).
- Ciclo de vida de incidentes: asignar, en progreso, notas, cierre con resolución obligatoria (Fase 3).
- Reglas de detección: fuerza bruta, cambio fuera de horario, cuenta de servicio, logs deshabilitados (Fase 4).
- Control de tormentas: límite de mensajes por minuto y por fuente en el receptor UDP (Fase 4).
- Generador de configuraciones Syslog comentadas para Cisco, Fortinet y Huawei (Fase 4).
- Consola simulada de solo lectura con lista permitida y bloqueo por defecto (Fase 4).
- Propuestas del asistente de IA con revisión y aprobación humana, ejecución simulada y verificación (Fase 4).
- Página de auditoría y política de defensa frente a agentes de IA (`docs/04_politica_ia.md`) (Fase 4).
- Integración continua con GitHub Actions (`.github/workflows/pruebas.yml`) (Fase 5).
- 76 pruebas automáticas.

### Seguridad
- Una fuente no autorizada nunca crea incidentes ni dispara reglas.
- Los títulos de incidentes y las propuestas se generan desde datos estructurados, nunca desde el texto del log.
- Un agente de IA no puede ejecutar comandos ni aprobar propuestas.

## [0.1.0] - 2026-10-06 — Alfa

### Agregado
- Estructura del proyecto, modelo de datos SQLite y equipos simulados (Fase 1).
- Inventario editable con validación y auditoría (Fase 2).
- Receptor Syslog UDP, importación de archivos y simulador de escenarios (Fase 2).
- Parser RFC 3164 / RFC 5424 y formatos Cisco IOS, FortiOS y Huawei VRP (Fase 2).
- Lista permitida de fuentes, deduplicación, detección de prompt injection y saneamiento (Fase 2).
- 31 pruebas automáticas.
