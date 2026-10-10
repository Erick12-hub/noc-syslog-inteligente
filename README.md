# NOC Syslog Inteligente

[![Pruebas](https://github.com/Erick12-hub/noc-syslog-inteligente/actions/workflows/pruebas.yml/badge.svg)](https://github.com/Erick12-hub/noc-syslog-inteligente/actions/workflows/pruebas.yml)

Aplicación web de administración y monitoreo de redes que recibe, clasifica y gestiona
eventos Syslog de equipos **Cisco, Fortinet y Huawei**, con controles de seguridad frente a
acciones no autorizadas de agentes de IA.

> Proyecto individual · Administración y Gestión de Redes · 2026-2 · Ing. John Harold Pérez Calderón
> **Versión:** v0.2.0 (MVP) · [CHANGELOG](CHANGELOG.md)
> ⚠️ **Todos los equipos y eventos incluidos son DATOS SIMULADOS** (prefijo `SIM-`, IP de documentación RFC 5737).

## Funcionalidades

| Módulo | Estado |
|---|---|
| Inventario editable de equipos (CRUD con validación y auditoría) | ✅ |
| Recepción Syslog por UDP (puerto 5514) | ✅ |
| Importación de archivos `.log` | ✅ |
| Parser RFC 3164 / RFC 5424 + formatos Cisco IOS, FortiOS y Huawei VRP | ✅ |
| Clasificación por equipo, fabricante, fecha, facility y severidad (0–7) | ✅ |
| Filtros por fecha, marca, equipo, severidad y marca de seguridad | ✅ |
| Lista permitida de fuentes, deduplicación, detección de prompt injection | ✅ |
| Dashboard: equipos por estado, eventos 24 h, críticos, alertas de seguridad, gráficas | ✅ |
| Incidentes automáticos (severidad 0–3 de fuente autorizada) con correlación | ✅ |
| Ciclo de vida de incidentes: asignar, seguimiento con notas, cerrar con resolución | ✅ |
| Generador de configuraciones Syslog comentadas (Cisco, Fortinet, Huawei) con NTP y verificación | ✅ |
| Consola simulada de solo lectura: lista permitida por fabricante, bloqueo por defecto, auditoría | ✅ |
| Reglas de detección: fuerza bruta, cambio fuera de horario, cuenta de servicio, logs deshabilitados | ✅ |
| Control de tormentas: límite de mensajes por minuto y por fuente | ✅ |
| Propuestas del asistente de IA con revisión y aprobación humana (flujo seguro de 8 pasos) | ✅ |
| Registro de auditoría consultable (solo lectura) | ✅ |

## Requisitos

- Python 3.10 o superior (probado con Python 3.14 en Windows, mediante Anaconda Prompt)
- Git

## Instalación (Windows)

```bat
git clone https://github.com/Erick12-hub/noc-syslog-inteligente.git
cd noc-syslog-inteligente
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
python manage.py init-db --seed
```

> Use siempre `python -m pip` y `python -m pytest`. En equipos con políticas de control de
> aplicaciones (Windows Device Guard), los ejecutables `pip.exe` y `pytest.exe` del entorno
> virtual pueden estar bloqueados por no estar firmados.

## Ejecución

Se usan **tres consolas**, todas con el entorno activado (`.venv\Scripts\activate`):

| Consola | Comando | Función |
|---|---|---|
| 1 | `python run.py` | Aplicación web → http://127.0.0.1:5000 (dashboard) |
| 2 | `python manage.py receiver` | Receptor Syslog UDP en 127.0.0.1:5514 |
| 3 | `python scripts\simulador.py --escenario todos` | Envía eventos simulados |

Otros comandos:

```bat
python scripts\simulador.py --listar                              :: escenarios disponibles
python scripts\simulador.py --escenario no_autorizado --modo directo
python scripts\simulador.py --escenario tormenta                 :: 150 mensajes: prueba el límite
python manage.py import-log samples\SIM-CORE-RTR01_cisco.log --ip 192.0.2.1
python manage.py check-db
```

## Pruebas

```bat
python -m pytest -v
```

76 pruebas automáticas: parser (PRI, Cisco, Huawei, Fortinet, RFC 5424, límites), ingesta
(lista permitida, deduplicación, prompt injection), API (CRUD, validaciones, filtros, importación),
incidentes (creación automática, correlación, transiciones de estado, cierre con resolución), dashboard
y seguridad (configuraciones, consola, reglas, tormentas, propuestas con aprobación humana, auditoría).

## Variables de configuración (`.env`)

| Variable | Valor por defecto | Uso |
|---|---|---|
| `STORM_MAX_PER_MINUTE` | `100` | Mensajes UDP por minuto y por fuente antes de descartar el exceso |
| `BUSINESS_HOURS` | `07-19` | Horario laboral para la regla `cambio_fuera_de_horario` |
| `LOCAL_UTC_OFFSET` | `-5` | Zona horaria local (Colombia) |
| `SERVICE_ACCOUNT_PREFIXES` | `svc_` | Prefijos de cuentas de servicio vigiladas |

## Seguridad

- **Sin secretos en el repositorio:** el archivo `.env` está en `.gitignore`; se publica solo `.env.example`.
- **Logs como datos no confiables:** el mensaje original se guarda y se muestra como texto; nunca se ejecuta.
- **Lista permitida de fuentes:** solo los equipos con `authorized = 1` son fuentes de confianza.
  La IP se toma del paquete UDP, no del nombre que trae el mensaje (evita suplantación).
- **Detección de prompt injection:** los mensajes con frases típicas de manipulación de IA se marcan.
- **Incidentes solo desde fuentes de confianza:** una IP no autorizada no puede generar incidentes, y el
  título de un incidente automático lo escribe el sistema, nunca se copia del texto del log.
- **Deduplicación:** los mensajes idénticos en 60 s se agrupan con un contador (control de tormentas).
- **Saneamiento:** se eliminan caracteres de control y saltos de línea (log injection) y se limita la longitud.
- **XSS:** la interfaz inserta los textos con `textContent`, nunca con `innerHTML`.
- **SQL injection:** todas las consultas usan parámetros `?`.
- **Los agentes de IA proponen, los humanos deciden:** el actor `asistente_ia` no puede ejecutar comandos
  ni aprobar propuestas; las acciones salen de un catálogo cerrado y requieren aprobación humana con comentario.
- **Consola de solo lectura simulada:** lista permitida por fabricante, bloqueo por defecto, bloqueo de
  comandos peligrosos y de encadenamiento (`; | & $ > <`).
- **Control de tormentas:** más de `STORM_MAX_PER_MINUTE` mensajes por minuto de una fuente → se descarta el exceso,
  se audita y se abre un incidente.
- **Auditoría:** inventario, importaciones, eventos sospechosos, reglas, consola, configuraciones y propuestas
  quedan en `audit_log` (solo inserción), consultable en la página Auditoría.

Política completa: [docs/04_politica_ia.md](docs/04_politica_ia.md).
- **Exposición mínima:** la aplicación y el receptor escuchan solo en `127.0.0.1`.

## Limitaciones conocidas

- Sin inicio de sesión ni roles (previsto para el Corte 3); las acciones se firman con `DEFAULT_OPERATOR`.
- La detección de prompt injection es heurística (por patrones): marca, no bloquea.
- La ejecución de propuestas y la consola son **simuladas**: no se conectan a ningún equipo.
- El límite de tormentas vive en memoria del receptor (se reinicia con él).
- Syslog por UDP no cifra ni autentica; en producción se recomienda TLS (RFC 5425) donde el equipo lo soporte.

## Documentación

- [Requisitos, objetivos y alcance](docs/01_requisitos.md)
- [Historias de usuario](docs/02_historias_usuario.md)
- [Arquitectura y modelo de datos](docs/03_arquitectura.md)
- [Política de defensa frente a agentes de IA](docs/04_politica_ia.md)
- [Bitácora de desarrollo](docs/bitacora.md)
- [Registro de cambios](CHANGELOG.md)
