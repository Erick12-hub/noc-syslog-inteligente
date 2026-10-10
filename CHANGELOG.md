# Registro de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
[versionado semántico](https://semver.org/lang/es/). Todos los datos son **SIMULADOS**.

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
