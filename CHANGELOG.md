# Registro de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
[versionado semántico](https://semver.org/lang/es/). Todos los datos son **SIMULADOS**.

## [0.5.0] - 2026-10-26 — Gestión de cambios e indicadores de operación (Fase 10)

Cuarta versión del Corte 3. Ningún cambio en un equipo se hace sin solicitud, evaluación de riesgo,
plan de rollback, aprobación de otra persona y verificación; todo queda en versiones de configuración
con su diff. El dashboard mide el MTTA y el MTTR contra objetivos por severidad. 564 pruebas
automáticas (423 en v0.4.0).

### Agregado
- Versiones de configuración por equipo (`config_versions`): el NOC lee `show running-config` (o
  `display current-configuration` / `show full-configuration`), **oculta los secretos** antes de guardar,
  normaliza las líneas que cambian solas y guarda una versión solo si cambió. Diff tipo `git diff`.
  Las versiones no se pueden modificar ni borrar (triggers). Comandos `device-config`, `device-configs`,
  `config-diff`.
- Solicitudes de cambio (página **Cambios**): comandos, justificación, **rollback obligatorio**,
  verificación de solo lectura y ventana. **Matriz de riesgo** impacto × probabilidad (1-9) con
  **impacto mínimo impuesto por los comandos** (`shutdown`, IP, rutas, ACL, VLAN, interfaz de gestión...).
  Comandos prohibidos aun con aprobación (guardar, borrar, reiniciar, credenciales, apagar el logging).
- Aprobación con separación de funciones: revisa un `admin_seguridad` distinto del solicitante, con
  comentario; riesgo alto requiere **dos personas distintas**. Revisiones inmutables.
- Ejecución verificada dentro de la ventana: línea base, detección de **deriva**, aplicación en el mismo
  equipo físico (número de serie), verificación (comandos y líneas presentes) y **rollback automático**
  con comparación contra la configuración de antes; incidente si el rollback no restaura. Rollback manual.
- Marca `cambio_autorizado`: un cambio aprobado en ejecución no dispara la regla "fuera de horario".
- Indicadores de operación en el dashboard y `manage.py metrics`: MTTA y MTTR (promedio y mediana),
  cumplimiento por severidad, incidentes vencidos, tendencia diaria, equipos con más incidentes y métricas
  de cambios (éxito, rollbacks, tiempo de aprobación). Filtros por periodo y por origen (reales / SIM).
- Modo simulado: la running-config refleja el inventario y los cambios aplicados (`sim_device_config`).
- Ícono del NOC en la pestaña del navegador.

### Cambiado
- `show running-config` sigue bloqueado en la sesión normal: solo lo usa la captura de versiones.
- Menú compactado para 9 enlaces a 1366 px.

### Corregido
- **Inicio de sesión imposible en Chrome y Edge** ("La sesión del formulario expiró"): la petición
  automática de `/favicon.ico` sin sesión borraba el token del formulario. Error presente desde v0.3.0;
  aparecía al limpiarse la caché del navegador.

## [0.4.0] - 2026-10-22 — Equipos del laboratorio, diagnóstico y consistencia (Fase 9)

Tercera versión del Corte 3. El NOC se conecta a equipos reales por cable de consola (o por SSH en
equipos fijos), los identifica por su número de serie, lee sus interfaces, ejecuta ping y traceroute
desde el propio equipo y revisa la consistencia de la red y de su auditoría. Probado con un router
Catalyst 8200L y un switch Catalyst 2960 del laboratorio (primera sesión de la marcha blanca,
2026-10-21). 423 pruebas automáticas (276 en v0.3.0).

### Agregado
- Gestor de conexiones (`app/connector.py`) con modos `ninguno`, `simulado`, `consola` y `ssh` (Netmiko).
  Por consola no se usan contraseñas (equipos prestados); por SSH la credencial solo vive en `.env` y la
  llave del equipo se fija la primera vez (si cambia, la sesión se aborta sin enviar comandos).
- Identificación del equipo físico por número de serie en cada sesión; alerta `device.serial_cambio` si
  responde otro equipo con el mismo nombre.
- Tablas `device_sessions` y `device_commands`: quién se conectó, a qué equipo físico, qué comandos envió,
  cuánto tardaron y la huella SHA-256 de cada salida. Historial por equipo en el Inventario.
- Comandos `device-session`, `device-sessions`, `device-interfaces`, `device-diag` y `check-consistency`.
- Configuración base desde cero para el router y el switch del laboratorio (`/api/config/baseline`):
  modo préstamo (sin credenciales ni guardado) o fijo (SSH con marcadores), direccionamiento manual o
  sugerido, máscara decimal o prefijo, interfaz de gestión editable y bloque de limpieza.
- Lectura de las interfaces reales del equipo (`show ip interface brief` / `display ip interface brief` /
  `get system interface physical`) con resumen de nuevas, cambiadas, sin cambios, ausentes y rechazadas; columnas
  IP y origen (manual / equipo).
- Diagnóstico desde el equipo: ping y traceroute con destino limitado a redes privadas y de documentación
  (`DIAG_ALLOWED_NETS`), máximo 5 por minuto, auditado y con resultado interpretado.
- Chequeo de consistencia (`app/consistency.py`, `/api/consistency`): reloj de cada equipo (desfase NTP
  por la mediana de sus últimos eventos), equipos sin eventos, interfaces desconocidas, marca
  inconsistente, IP del inventario que el equipo no tiene e IP duplicadas.
- Verificación automática de la cadena de auditoría cada `CONSISTENCY_INTERVAL_MINUTES` en el receptor;
  si se rompe se abre un incidente de severidad 1 (uno solo mientras siga abierto).
- Panel «Consistencia de la red» y «Reloj de los equipos» en el dashboard, con botón «Revisar ahora».
- Salidas de ejemplo de un C8200 y un 2960 (`samples/cli/`) para el modo simulado.
- Plan de la sesión de laboratorio (`docs/laboratorio/plan_sesion_laboratorio.md`).

### Cambiado
- La configuración base se entrega en trozos de 5 líneas o menos, cada uno con su botón Copiar.
- En el router la zona horaria se configura antes de `clock set`.
- `no ip domain lookup` (con espacio, válido en IOS XE 17) dentro de `configure terminal`.
- `ping` y `traceroute` no están en la lista general de la consola: solo se aceptan por Diagnóstico,
  después de validar el destino.

### Corregido
- Mensajes en español cuando el puerto de consola no existe o está en uso (PuTTY abierto).
- Al pegar toda la configuración por consola a 9600 baudios se perdían líneas (hallazgo del laboratorio).
- El router quedaba 5 horas atrás al escribir la hora antes de la zona (hallazgo del laboratorio).

## [0.3.0] - 2026-10-19 — Seguridad de acceso, auditoría encadenada e interfaces (Fase 8)

Segunda versión del Corte 3. Cada acción queda firmada por un usuario real con un rol, la
auditoría no se puede alterar sin que se note y el inventario conoce las interfaces de cada
equipo. 276 pruebas automáticas (168 en v0.2.1).

### Agregado
- Usuarios con roles `operador`, `auditor` y `admin_seguridad`; inicio y cierre de sesión (`/login`, `/logout`).
- Contraseñas con hash scrypt y política mínima (10 caracteres, letras y números, sin el nombre de usuario).
- Bloqueo de la cuenta tras 5 intentos fallidos durante 15 minutos; mensaje genérico si el usuario no existe.
- Token anti-CSRF en toda petición que cambia datos; rechazos por CSRF o por rol quedan auditados.
- Control de permisos central (`app/auth.py`): tabla de reglas por ruta y regla por defecto segura.
- Separación de funciones: solo `admin_seguridad` aprueba propuestas y nunca las propias.
- Comandos `create-user`, `users`, `unlock` y `verify-audit` en `manage.py`.
- Auditoría encadenada con SHA-256 (`prev_hash`, `hash`), triggers de solo inserción y verificación de integridad
  (API `/api/audit/verify` y botón en la página Auditoría).
- `scripts/simular_alteracion_auditoria.py`: demuestra la detección sobre una COPIA de la base.
- Ventana **Seguridad** (solo administrador): resumen de 24 h, cuentas bloqueadas, usuarios (crear, rol, activar,
  desbloquear, restablecer contraseña) y estado de la cadena.
- Tabla `interfaces` por equipo, gestionada desde Inventario, con validación de nombres por fabricante
  (Cisco, Huawei, FortiGate) y normalización (`Gi0/1` → `GigabitEthernet0/1`).
- Marca `interfaz_desconocida` y su filtro en Eventos.

### Cambiado
- El responsable de cada acción en la auditoría es el usuario de la sesión (antes, `DEFAULT_OPERATOR`).
- Menú y botones según el rol; el auditor ve la aplicación en modo de solo lectura.
- La huella de deduplicación incluye la interfaz.

### Corregido
- El auditor recibía 403 al cerrar sesión.
- Una cuenta bloqueada mostraba 0 intentos fallidos.
- Dos interfaces distintas con el mismo tipo de evento (`Gi0/0/1 down` y `Gi0/0/9 down`) se agrupaban como
  un solo evento repetido, y un evento de una interfaz no registrada podía quedar oculto.

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
