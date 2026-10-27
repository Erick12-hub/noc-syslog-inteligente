# Manual técnico — NOC Syslog Inteligente v1.0

Para quien **instala, mantiene o amplía** el NOC. El uso diario está en [manual_usuario.md](manual_usuario.md),
la instalación en [despliegue.md](despliegue.md) y la vuelta atrás en [rollback.md](rollback.md).
El diseño original (requisitos, historias, arquitectura y política de IA) está en `docs/01` a `docs/04`.

## 1. Arquitectura

Monolito en capas, en un solo PC: **Flask** (API + páginas), **SQLite** en modo WAL, JavaScript sin
frameworks en el navegador y dos procesos.

```
 Equipos (Cisco/Fortinet/Huawei)          Operador (navegador)
        │ UDP 5514                                │ HTTP 5000
        ▼                                         ▼
 ┌──────────────────┐                   ┌──────────────────────┐
 │ manage.py        │                   │ serve.py (waitress)  │
 │ receiver         │                   │ Flask: API + páginas │
 │  ingest()        │                   │ sesión · CSRF · rol  │
 │  consistencia c/ │                   │ cambios · consola ·  │
 │  10 min          │                   │ conexiones · IA      │
 └────────┬─────────┘                   └──────────┬───────────┘
          │            ┌───────────────┐           │
          └──────────► │ data/noc.db   │ ◄─────────┘
                       │ SQLite (WAL)  │
                       │ auditoría     │──► Telegram (avisos, opcional)
                       │ encadenada    │
                       └───────────────┘
```

| Proceso | Comando | Función |
|---|---|---|
| Web | `python serve.py` | waitress, nunca en modo depuración, `WEB_THREADS` hilos, encabezado `Server` sin versión |
| Receptor | `python manage.py receiver` | UDP `SYSLOG_HOST:SYSLOG_PORT`; cada 10 min revisa consistencia y cadena de auditoría |
| Desarrollo | `python run.py` | Servidor de Flask; depuración solo con `FLASK_DEBUG=1`. **Nunca en operación** |

## 2. Camino de un mensaje Syslog (`app/ingest.py`)

1. **Control de tormentas** (solo UDP): más de `STORM_MAX_PER_MINUTE` por IP → se descarta, auditoría
   `syslog.tormenta` e incidente de severidad 2.
2. **Parser** (`syslog_parser.py`): PRI → facility y severidad; RFC 3164/5424; Cisco `%FAC-SEV-MNEM`,
   Huawei `%%01MOD/SEV/MNEM`, FortiOS `clave=valor`; interfaz y puertos; caracteres de control removidos.
3. **Fecha:** a UTC; posterior a la recepción + `FUTURE_TOLERANCE_SECONDS` → `fecha_futura`.
4. **Inventario:** IP desconocida o no autorizada → marcas; fabricante del texto ≠ inventario →
   `marca_inconsistente`; interfaz que el equipo no tiene → `interfaz_desconocida`.
5. **Seguridad** (`security.py`): huella para deduplicar; detección de prompt injection con
   normalización NFKC y sin caracteres invisibles → `posible_prompt_injection`.
6. **Reglas** (`rules.py`): fuerza bruta, cambio fuera de horario (salvo cambio autorizado por el NOC en
   los 10 min siguientes), cuenta de servicio, logs deshabilitados.
7. **Incidente:** severidad 0–3 de fuente autorizada; correlación por clave para no duplicar.
8. **Aviso** (`notify.py`): severidad ≤ `NOTIFY_MIN_SEVERITY` → Telegram, con agrupación y límite.

## 3. Módulos

| Módulo | Responsabilidad |
|---|---|
| `__init__.py` | Fábrica `create_app`, registro de blueprints, `APP_VERSION` |
| `config.py` | Lee `.env` (python-dotenv); rutas relativas a la raíz del proyecto |
| `db.py` | Conexión (WAL, claves foráneas), esquema, migraciones, índices, **auditoría encadenada** |
| `auth.py` | Usuarios (scrypt), login con bloqueo, sesión, CSRF, control por rol (`RULES`, `PREFIX_RULES`) |
| `admin_api.py`, `audit_api.py` | Ventana de seguridad; consulta y verificación de la auditoría |
| `receiver.py`, `ingest.py`, `syslog_parser.py`, `security.py`, `rules.py` | Recepción y procesamiento de Syslog |
| `devices.py`, `interfaces.py`, `events.py`, `incidents.py`, `dashboard.py` | Inventario, eventos, incidentes y tablero |
| `connector.py` | Sesiones con equipos: `simulado`, `consola` (Netmiko serial) y `ssh`; identidad por serie |
| `diagnostics.py`, `consistency.py` | Ping/traceroute desde el equipo; NTP, equipos callados, IP duplicadas |
| `configgen.py`, `console.py` | Configuraciones Syslog/NTP y base de laboratorio; consola de solo lectura |
| `configversions.py` | Versiones de configuración, ocultar secretos, normalizar y diff |
| `changes.py`, `changeexec.py` | Solicitudes de cambio, riesgo, ventana; aprobación, ejecución, verificación y rollback |
| `metrics.py` | MTTA, MTTR, SLA por severidad, vencidos, cambios |
| `notify.py` | Avisos por Telegram (o simulados), hilo de envío, agrupación y límite |
| `proposals.py` | Propuestas del asistente de IA con aprobación humana, interruptor y límite |
| `backup.py` | Respaldo, verificación y restauración de la base |
| `validation.py`, `timeutil.py`, `seed.py`, `views.py` | Validación de parámetros, fechas, datos SIM, páginas |

## 4. Base de datos (`app/schema.sql`)

| Tabla | Contenido | Protección |
|---|---|---|
| `severities` | Severidades 0–7 | Se recarga en cada `init-db` |
| `devices`, `interfaces` | Inventario | CHECK de estado; IP única |
| `syslog_events` | Eventos (texto crudo y saneado, marcas, huella) | Índices por fecha, equipo, severidad |
| `incidents`, `incident_notes` | Incidentes y seguimiento | Transiciones validadas en la API |
| `action_proposals` | Propuestas de la IA | Flujo pendiente → aprobada → ejecutada → verificada |
| `device_sessions`, `device_commands` | Trazabilidad de conexiones | Salida saneada (sin secretos) |
| `config_versions` | Versiones de configuración (con `<oculto>`) | Triggers: no se modifican ni borran |
| `change_requests`, `change_approvals` | Cambios y aprobaciones | Triggers en aprobaciones |
| `sim_device_config` | running-config de los equipos SIM | Solo modo simulado |
| `users` | Usuarios (hash scrypt, rol, bloqueo) | Nunca se guarda la contraseña |
| `notifications` | Avisos (sin el texto del log) | Estado y error sin token |
| `audit_log` | Auditoría | **Solo inserción** (triggers) y cadena SHA-256 |

**Migraciones:** `init_db()` es idempotente: crea lo que falta y agrega columnas nuevas (`MIGRATIONS`,
`ALTER TABLE ADD COLUMN`); nunca borra datos. Por eso actualizar el NOC es seguro, pero **volver a una
versión anterior se hace restaurando un respaldo** ([rollback.md](rollback.md)).

**Auditoría encadenada:** `hash_n = SHA-256(hash_{n-1} | ts | actor | acción | entidad | id | detalle | resultado)`.
`verify_audit_chain()` recalcula todo y devuelve el primer registro roto. El último hash se anota en la
bitácora al cierre de cada fase, porque un recorte del final no rompe la cadena.

## 5. Configuración (`.env`)

Se copia de `.env.example`. **Nunca** se sube a GitHub (`.gitignore`) ni se muestra en capturas.

| Grupo | Variables | Notas |
|---|---|---|
| Web | `SECRET_KEY`, `WEB_HOST`, `WEB_PORT`, `WEB_THREADS`, `FLASK_DEBUG` | `SECRET_KEY` aleatoria; `FLASK_DEBUG=0` |
| Base | `DATABASE_PATH` | `data/noc.db` |
| Receptor | `SYSLOG_HOST`, `SYSLOG_PORT`, `STORM_MAX_PER_MINUTE` | 5514 evita permisos de administrador |
| Sesión | `MAX_LOGIN_ATTEMPTS`, `LOCKOUT_MINUTES`, `SESSION_HOURS`, `PASSWORD_MIN_LENGTH`, `SESSION_COOKIE_SECURE` | Secure=1 solo con HTTPS |
| Reglas | `BUSINESS_HOURS`, `LOCAL_UTC_OFFSET`, `FUTURE_TOLERANCE_SECONDS`, `SERVICE_ACCOUNT_PREFIXES` | Colombia: −5 |
| Equipos | `SSH_USERNAME`, `SSH_PASSWORD`, `SSH_PORT`, `CONSOLE_BAUDRATE`, `CONNECT_TIMEOUT`, `COMMAND_TIMEOUT` | SSH vacío con equipos prestados |
| Diagnóstico | `DIAG_ALLOWED_NETS`, `DIAG_MAX_PER_MINUTE`, `DIAG_TIMEOUT` | Lista de redes permitidas |
| Consistencia | `NTP_WARN_SECONDS`, `NTP_CRIT_SECONDS`, `CONSISTENCY_SILENT_HOURS`, `CONSISTENCY_INTERVAL_MINUTES` | |
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `NOTIFY_MIN_SEVERITY`, `NOTIFY_SIMULATE`, `NOTIFY_MAX_PER_MINUTE`, `NOTIFY_GROUP_MINUTES`, `NOC_URL` | El token es un **secreto** |
| IA | `AI_ASSISTANT_ENABLED`, `AI_MAX_SUGGESTIONS_PER_MINUTE` | 0 = asistente apagado |
| IA local | `LOCAL_AI_ENABLED`, `LOCAL_AI_URL`, `LOCAL_AI_MODEL`, `LOCAL_AI_TIMEOUT`, `LOCAL_AI_DIR` | Solo URL local (127.0.0.1) |
| Respaldos | `BACKUP_DIR`, `BACKUP_KEEP` | Fuera de GitHub |

## 6. Comandos de administración (`manage.py`)

| Comando | Uso |
|---|---|
| `init-db [--seed]` | Crear/actualizar tablas; `--seed` carga los equipos SIM |
| `check-db` | Tablas y cantidad de registros |
| `receiver` | Receptor Syslog UDP |
| `import-log ARCHIVO --ip IP` | Importar un archivo `.log` |
| `create-user U --rol R [--nombre N]`, `users`, `unlock U` | Usuarios (contraseña con getpass, nunca en el historial) |
| `verify-audit` | Verificar la cadena de auditoría |
| `device-session`, `device-sessions`, `device-interfaces`, `device-diag` | Conexión, historial, interfaces y diagnóstico |
| `check-consistency` | Reloj, consistencia y cadena |
| `device-config`, `device-configs`, `config-diff A B` | Versiones de configuración |
| `metrics [--dias 7\|30\|90\|0] [--origen ...]` | Indicadores de operación |
| `notify-test`, `telegram-chat-id` | Telegram |
| `ia-estado`, `ia-borrador bitacora\|informe [--dias N]` | Asistente de IA local ([ia_local.md](ia_local.md)) |
| `backup [--nota]`, `backups`, `verify-backup F`, `restore F --confirmar` | Respaldos |

Scripts: `scripts/simulador.py` (eventos SIM), `scripts/simular_alteracion_auditoria.py` (demostración
de cadena rota, en copia), `scripts/prueba_carga.py` y `scripts/reporte_pruebas.py`.

## 7. Controles de seguridad

| Amenaza | Control |
|---|---|
| Acceso no autorizado | Login obligatorio, scrypt, bloqueo tras 5 intentos, mensaje genérico y tiempo igualado |
| Abuso de privilegios | Roles por endpoint; lo no declarado: GET para todos, escritura solo OPS; separación de funciones en aprobaciones |
| CSRF | Token por sesión en formularios y en el encabezado `X-CSRF-Token` |
| Fuentes falsas / suplantación | Lista permitida, `marca_inconsistente`, `interfaz_desconocida`, identidad del equipo por serie |
| Inundación | Control de tormentas por IP; límites en diagnóstico, IA y avisos |
| Prompt injection en logs | Detección normalizada; los logs son **datos**; la IA solo propone y no puede pedir cambios |
| Cambios peligrosos | Comandos prohibidos, rollback obligatorio, ventana, deriva, serie, verificación y rollback automático |
| Secretos | `.env` fuera de Git; contraseñas de configuración ocultas; avisos sin texto del log; errores sin token |
| Manipulación de evidencia | Auditoría de solo inserción con cadena SHA-256 y verificación periódica (incidente sev. 1 si se rompe) |
| Pérdida de datos | Respaldos verificados (SHA-256, integrity_check, cadena) y restauración con respaldo de seguridad |

## 8. Pruebas

```bat
python -m pytest -q                    :: 623 pruebas, bases temporales, sin red
python scripts\reporte_pruebas.py      :: docs/pruebas/reporte_pruebas.md por categoría
python scripts\prueba_carga.py --reporte
```

GitHub Actions (`.github/workflows/pruebas.yml`) corre la batería en Python 3.12 y 3.14 en cada push a
`main`/`develop` y en cada PR a `main`. `tests/conftest.py` anula el token de Telegram y usa un hash rápido.

## 9. Cómo ampliar el NOC

| Quiero… | Dónde | Además |
|---|---|---|
| Un fabricante nuevo | `syslog_parser.py` (detección y formato), `console.py` (`ALLOWLIST`), `configgen.py`, CHECK de `devices.vendor` | Muestras en `samples/` y pruebas en `test_parser.py` |
| Una regla de detección | `rules.py`: entrada en `RULES` (severidad y título) y su condición de detección | Prueba en `test_seguridad.py` |
| Un endpoint | Blueprint del módulo; si es sensible, entrada en `auth.RULES` | Auditar la acción con `db.audit()` |
| Una columna | `schema.sql` y `MIGRATIONS` en `db.py` | Nunca borrar columnas: compatibilidad con respaldos |
| Un comando prohibido en cambios | `changes.FORBIDDEN` | Prueba en `test_cambios.py` |

Convenciones: ramas `feature/...` → `develop` → `main`, Conventional Commits sin tildes, cada commit con
sus pruebas en verde, versión en `app/__init__.py` y `CHANGELOG.md`.
