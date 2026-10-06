# 1. Problema, objetivos, alcance y requisitos

**Proyecto:** NOC Syslog Inteligente · **Versión del documento:** v0.2.0 (MVP, Corte 2)
**Asignatura:** Administración y Gestión de Redes · 2026-2

## 1.1 Planteamiento del problema

En una red con equipos de varios fabricantes (Cisco, Fortinet, Huawei), cada equipo genera
mensajes Syslog con formatos y niveles distintos. Si estos mensajes no se centralizan, el
equipo de operación no se entera a tiempo de fallas, cambios de configuración o accesos
no autorizados, y no queda trazabilidad de quién hizo qué.

A esto se suma un riesgo nuevo: los **agentes de inteligencia artificial** con acceso a la
red pueden ejecutar comandos no autorizados, de forma maliciosa o por error, o ser
manipulados con instrucciones escondidas dentro de los propios logs (*prompt injection*).
Se necesita una herramienta que centralice los eventos, los clasifique, permita gestionar
incidentes y aplique controles explícitos sobre lo que cualquier agente, humano o IA,
puede hacer.

## 1.2 Objetivos

**Objetivo general:** desarrollar una aplicación web tipo NOC que reciba, clasifique y
visualice eventos Syslog de equipos multivendor, permita gestionar incidentes y aplique
una política de seguridad que impida que acciones automatizadas o de IA se ejecuten sin
validación y aprobación humana.

**Objetivos específicos:**

1. Mantener un inventario editable de los dispositivos de red.
2. Recibir por UDP o importar desde archivo mensajes Syslog y clasificarlos por dispositivo,
   fabricante, fecha, facility y severidad (0–7, RFC 5424).
3. Presentar un dashboard con el estado de los equipos, los eventos recientes y críticos, y
   los incidentes, con filtros.
4. Gestionar el ciclo de vida de los incidentes: creación, asignación, seguimiento y cierre.
5. Generar configuraciones Syslog comentadas para Cisco, Fortinet y Huawei.
6. Ofrecer una consola simulada de solo lectura con comandos permitidos y bloqueados.
7. Definir y aplicar una política inicial de defensa frente a acciones de agentes de IA,
   con auditoría de todas las acciones.

## 1.3 Alcance y limitaciones (v0.2.0)

| Incluido en el MVP | Fuera del MVP (pendiente para v1.0.0) |
|---|---|
| Inventario CRUD | Login y control de acceso por roles |
| Receptor UDP (puerto 5514) e importación de archivos | Transporte TLS (RFC 5425) |
| Parser RFC 3164 / RFC 5424 | Alertas por Telegram |
| Dashboard, filtros, incidentes | Conexión SSH real a equipos |
| Consola **simulada** (no se conecta a ningún equipo) | Marcha blanca con equipos reales |
| Lista de fuentes permitidas, deduplicación, límite de frecuencia | Respaldo y retención automatizados |
| Auditoría de acciones | Despliegue en servidor |

**Datos:** todos los dispositivos y eventos de esta versión son **SIMULADOS**. Usan
nombres con prefijo `SIM-` e IP de documentación según la RFC 5737
(192.0.2.0/24, 198.51.100.0/24 y 203.0.113.0/24), y están marcados con `is_simulated = 1`.

## 1.4 Requisitos funcionales

| ID | Requisito | Prioridad |
|---|---|---|
| RF-01 | Registrar, consultar, editar y eliminar equipos (nombre, IP, marca, modelo, versión, ubicación, estado, fecha de actualización) | Alta |
| RF-02 | Recibir mensajes Syslog por UDP e importarlos desde archivo de texto | Alta |
| RF-03 | Extraer del PRI la facility y la severidad (PRI = facility × 8 + severidad) | Alta |
| RF-04 | Asociar cada evento al equipo del inventario por IP de origen | Alta |
| RF-05 | Dashboard con estado de equipos, eventos recientes, eventos críticos e incidentes | Alta |
| RF-06 | Filtrar eventos por rango de fechas, marca, equipo y severidad | Alta |
| RF-07 | Crear, asignar, dar seguimiento (notas) y cerrar incidentes; el cierre exige una resolución | Alta |
| RF-08 | Crear incidentes automáticamente para severidades 0–3 de fuentes autorizadas | Media |
| RF-09 | Generar configuraciones Syslog comentadas para Cisco, Fortinet y Huawei | Alta |
| RF-10 | Consola simulada con lista de comandos permitidos (solo lectura); bloquear y auditar el resto | Alta |
| RF-11 | Marcar los eventos de fuentes no incluidas en la lista permitida | Alta |
| RF-12 | Deduplicar eventos repetidos y limitar la frecuencia por fuente (control de tormentas) | Media |
| RF-13 | Registrar propuestas de acción que solo avanzan con aprobación humana | Media |
| RF-14 | Registrar en la auditoría toda acción relevante (actor, acción, fecha, resultado) | Alta |

## 1.5 Requisitos no funcionales

| ID | Requisito |
|---|---|
| RNF-01 | **Seguridad:** sin secretos en el código; configuración por `.env`, excluido del repositorio |
| RNF-02 | **Seguridad:** los logs se tratan como datos no confiables; nunca se ejecutan ni se usan como instrucciones |
| RNF-03 | **Seguridad:** la aplicación escucha solo en 127.0.0.1 en el MVP |
| RNF-04 | **Reproducibilidad:** se instala desde cero siguiendo únicamente el README |
| RNF-05 | **Mantenibilidad:** código comentado y organizado por módulos |
| RNF-06 | **Trazabilidad:** fechas en UTC con formato ISO 8601; auditoría de solo inserción |
| RNF-07 | **Portabilidad:** Python 3.10+ y SQLite, sin servicios externos |
