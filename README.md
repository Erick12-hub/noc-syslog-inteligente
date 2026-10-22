# NOC Syslog Inteligente

[![Pruebas](https://github.com/Erick12-hub/noc-syslog-inteligente/actions/workflows/pruebas.yml/badge.svg)](https://github.com/Erick12-hub/noc-syslog-inteligente/actions/workflows/pruebas.yml)

Aplicación web de administración y monitoreo de redes que recibe, clasifica y gestiona
eventos Syslog de equipos **Cisco, Fortinet y Huawei**, con controles de seguridad frente a
acciones no autorizadas de agentes de IA.

> Proyecto individual · Administración y Gestión de Redes · 2026-2 · Ing. John Harold Pérez Calderón
> **Versión:** v0.4.0 (equipos del laboratorio, diagnóstico y consistencia) · [CHANGELOG](CHANGELOG.md)
> ⚠️ **Los equipos y eventos incluidos en el repositorio son DATOS SIMULADOS** (prefijo `SIM-`, IP de documentación RFC 5737).
> Desde v0.4.0 el NOC también trabaja con equipos **reales y autorizados** del laboratorio (sin `SIM-`).

## Funcionalidades

| Módulo | Estado |
|---|---|
| Inventario editable de equipos (CRUD con validación y auditoría) | ✅ |
| Interfaces de cada equipo con validación por fabricante y marca `interfaz_desconocida` | ✅ |
| Recepción Syslog por UDP (puerto 5514) | ✅ |
| Importación de archivos `.log` | ✅ |
| Parser RFC 3164 / RFC 5424 + formatos Cisco IOS, FortiOS y Huawei VRP | ✅ |
| Clasificación por equipo, fabricante, fecha, facility y severidad (0–7) | ✅ |
| Filtros por fecha (hora de Colombia, sin fechas futuras), marca, equipo, severidad, interfaz, puerto y marca de seguridad, con paginación | ✅ |
| Interfaz y puertos de origen/destino en cada evento | ✅ |
| Detección de reloj desfasado (`fecha_futura`) y de marca inconsistente (posible suplantación) | ✅ |
| Validación de parámetros: un valor inválido responde 400 con todos los errores | ✅ |
| Tema claro y oscuro | ✅ |
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
| Inicio de sesión con roles (operador, auditor, administrador de seguridad), bloqueo y CSRF | ✅ |
| Auditoría encadenada con SHA-256, protegida contra cambios y con verificación de integridad | ✅ |
| Ventana de seguridad: usuarios, bloqueos, intentos fallidos y acciones bloqueadas | ✅ |
| Conexión con los equipos por consola (sin contraseñas), SSH (equipos fijos) o simulada, con identificación por número de serie e historial de sesiones | ✅ |
| Configuración base desde cero para router y switch del laboratorio, en trozos para pegar por consola | ✅ |
| Lectura de las interfaces reales del equipo y comparación con el inventario | ✅ |
| Diagnóstico desde el equipo: ping y traceroute con destino validado y límite por minuto | ✅ |
| Consistencia de la red: reloj (NTP) de cada equipo, equipos callados, IP duplicadas o fuera del inventario | ✅ |
| Verificación automática de la cadena de auditoría con incidente de severidad 1 si se rompe | ✅ |

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
python manage.py create-user admin --rol admin_seguridad --nombre "Su nombre"
```

El último comando crea el **primer usuario** (no hay usuarios ni contraseñas por defecto).
La contraseña se escribe en la consola sin mostrarse: mínimo 10 caracteres, con letras y
números, sin contener el nombre de usuario. Luego, desde la misma consola:

```bat
python manage.py create-user operador1 --rol operador --nombre "Turno noche"
python manage.py create-user auditor1 --rol auditor
python manage.py users                    :: lista usuarios, estado y último ingreso
python manage.py unlock operador1         :: desbloquea una cuenta tras 5 intentos fallidos
```

| Rol | Puede |
|---|---|
| `operador` | Inventario, eventos, incidentes, consola, crear/ejecutar/verificar propuestas |
| `auditor` | Ver todo, incluida la auditoría. **Solo lectura** |
| `admin_seguridad` | Todo + aprobar propuestas (nunca las propias) + usuarios |

> Use siempre `python -m pip` y `python -m pytest`. En equipos con políticas de control de
> aplicaciones (Windows Device Guard), los ejecutables `pip.exe` y `pytest.exe` del entorno
> virtual pueden estar bloqueados por no estar firmados.

## Ejecución

Se usan **tres consolas**, todas con el entorno activado (`.venv\Scripts\activate`):

| Consola | Comando | Función |
|---|---|---|
| 1 | `python serve.py` | Aplicación web con waitress, sin depuración → http://127.0.0.1:5000 (operación y marcha blanca) |
| 2 | `python manage.py receiver` | Receptor Syslog UDP en 127.0.0.1:5514 |
| 3 | `python scripts\simulador.py --escenario todos` | Envía eventos simulados |

> Para **desarrollo** se puede usar `python run.py` (servidor de Flask). El modo
> depuración solo se activa con `FLASK_DEBUG=1` en el `.env`; nunca durante la operación.

Otros comandos:

```bat
python scripts\simulador.py --listar                              :: escenarios disponibles
python scripts\simulador.py --escenario no_autorizado --modo directo
python scripts\simulador.py --escenario tormenta                 :: 150 mensajes: prueba el límite
python manage.py import-log samples\SIM-CORE-RTR01_cisco.log --ip 192.0.2.1
python manage.py check-db
python manage.py check-consistency                               :: reloj, consistencia y cadena de auditoría
```

### Equipos reales (laboratorio)

En el Inventario, cada equipo tiene un **modo de conexión**: `ninguno` (solo envía Syslog), `simulado`,
`consola` (cable USB, puerto `COMn`, **sin contraseñas**: equipos prestados) o `ssh` (equipos fijos; usuario y
contraseña solo en `.env`). El botón **Conexión** identifica el equipo físico, lee sus interfaces y hace
ping/traceroute. Por consola:

```bat
python manage.py device-session LAB-RTR01                       :: identifica el equipo (show version)
python manage.py device-sessions LAB-RTR01                      :: historial de conexiones
python manage.py device-interfaces LAB-RTR01                    :: lee las interfaces reales
python manage.py device-diag LAB-RTR01 ping 192.168.100.10       :: ping desde el equipo
```

Cierre PuTTY antes de conectar desde el NOC (el puerto COM no se comparte). Para recibir Syslog de los
equipos, el receptor debe escuchar en la IP del PC en la red del laboratorio, solo en esa ventana:
`set SYSLOG_HOST=192.168.100.10` y luego `python manage.py receiver`. El paso a paso, el firewall y la
limpieza están en [docs/laboratorio/plan_sesion_laboratorio.md](docs/laboratorio/plan_sesion_laboratorio.md).

## Pruebas

```bat
python -m pytest -v
```

423 pruebas automáticas: parser (PRI, Cisco, Huawei, Fortinet, RFC 5424, límites), ingesta
(lista permitida, deduplicación, prompt injection), API (CRUD, validaciones, filtros, importación),
incidentes (creación automática, correlación, transiciones de estado, cierre con resolución), dashboard
y seguridad (configuraciones, consola, reglas, tormentas, propuestas con aprobación humana, auditoría).
Desde v0.2.1: interfaz y puertos, fechas y zona horaria, validación de parámetros, coherencia
equipo-marca, índices y WAL, paginación, servidor waitress y tema claro/oscuro.
Desde v0.3.0: sesión, bloqueo, CSRF, roles y separación de funciones, cadena de auditoría
(alteración y borrado detectados), ventana de seguridad e interfaces por equipo.
Desde v0.4.0: gestor de conexiones (consola, SSH, simulado; número de serie, llave SSH, bloqueos),
configuración base, interfaces reales, diagnóstico (destinos y límite) y consistencia (reloj, IP, cadena).

## Variables de configuración (`.env`)

| Variable | Valor por defecto | Uso |
|---|---|---|
| `STORM_MAX_PER_MINUTE` | `100` | Mensajes UDP por minuto y por fuente antes de descartar el exceso |
| `BUSINESS_HOURS` | `07-19` | Horario laboral para la regla `cambio_fuera_de_horario` |
| `LOCAL_UTC_OFFSET` | `-5` | Zona horaria local (Colombia) |
| `SERVICE_ACCOUNT_PREFIXES` | `svc_` | Prefijos de cuentas de servicio vigiladas |
| `SSH_USERNAME` / `SSH_PASSWORD` | (vacío) | Solo equipos fijos por SSH. **Nunca** en GitHub ni en capturas |
| `CONSOLE_BAUDRATE` | `9600` | Velocidad del cable de consola |
| `DIAG_ALLOWED_NETS` | redes privadas y RFC 5737 | Destinos permitidos para ping y traceroute |
| `DIAG_MAX_PER_MINUTE` | `5` | Diagnósticos por minuto, usuario y equipo |
| `NTP_WARN_SECONDS` / `NTP_CRIT_SECONDS` | `2` / `60` | Desfase de reloj para aviso y crítico |
| `CONSISTENCY_INTERVAL_MINUTES` | `10` | Cada cuánto el receptor revisa consistencia y cadena (0 = no) |

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
- **Auditoría:** inventario, importaciones, eventos sospechosos, reglas, consola, configuraciones, propuestas,
  sesiones y usuarios quedan en `audit_log`, consultable en la página Auditoría.
- **Auditoría encadenada (v0.3.0):** cada registro guarda el SHA-256 del anterior; triggers de SQLite rechazan
  `UPDATE` y `DELETE`. `python manage.py verify-audit` o el botón *Verificar integridad* detectan un registro
  alterado o borrado. Guarde el último hash fuera de la base (bitácora) para detectar un recorte del final.
- **Sesión y roles (v0.3.0):** sin usuarios por defecto; contraseñas con scrypt; bloqueo tras 5 intentos durante
  15 minutos; mismo mensaje si el usuario no existe; cookie `HttpOnly` y `SameSite=Lax`; token CSRF en cada
  petición que cambia datos; permisos por rol en un solo punto (`app/auth.py`); nadie aprueba su propia propuesta.
- **Interfaces por equipo (v0.3.0):** si un evento menciona una interfaz que el equipo no tiene registrada, se marca
  `interfaz_desconocida` y se audita (inventario desactualizado o mensaje fabricado).
- **Conexión con los equipos (v0.4.0):** por consola no hay contraseñas; por SSH la credencial solo está en `.env`
  y la llave del equipo se fija la primera vez (si cambia, se aborta). Cada sesión identifica el equipo físico por
  su número de serie y guarda cada comando con la huella SHA-256 de su salida. Solo comandos de lectura de la lista
  permitida; la salida del equipo es un dato no confiable (solo se extraen campos con patrones fijos).
- **Diagnóstico acotado (v0.4.0):** ping y traceroute solo hacia redes privadas o de documentación, 5 por minuto,
  y solo por la ruta de Diagnóstico: los equipos no se usan para sondear Internet.
- **Consistencia (v0.4.0):** el receptor verifica la cadena de auditoría cada 10 minutos; si se rompe abre un
  incidente de severidad 1.

Política completa: [docs/04_politica_ia.md](docs/04_politica_ia.md).
- **Exposición mínima:** la aplicación y el receptor escuchan solo en `127.0.0.1`. En el laboratorio el receptor
  escucha en la IP del PC en esa red (nunca `0.0.0.0`) y el firewall solo acepta la red del laboratorio.

## Limitaciones conocidas

- Las acciones por consola de comandos (`manage.py`, receptor UDP) se firman con `DEFAULT_OPERATOR`; las de la web, con el usuario de la sesión.
- La cookie de sesión no lleva la marca `Secure` porque el NOC se sirve por HTTP en 127.0.0.1; con HTTPS se activa `SESSION_COOKIE_SECURE=1`.
- Los eventos guardados antes de v0.2.1 no tienen interfaz ni puertos: los datos no se recalculan.
- El hash de la cadena de auditoría no usa clave secreta: quien tenga acceso al archivo podría recalcular la cadena;
  lo delata el hash guardado fuera de la base (bitácora).
- La conexión por consola solo está disponible para Cisco; Huawei y Fortinet se probaron con salidas de ejemplo.
- El desfase de reloj se mide contra la hora del PC del NOC, que debe estar sincronizada; un equipo que no envía
  eventos no se puede medir.
- La marca `interfaz_desconocida` solo se aplica a equipos que tienen interfaces registradas.
- La fecha de mensajes sin zona horaria se interpreta en hora de Colombia (los equipos del laboratorio envían la zona).
- La detección de prompt injection es heurística (por patrones): marca, no bloquea.
- La ejecución de propuestas y la consola de la página Consola siguen **simuladas**; la conexión real es solo de
  lectura y diagnóstico (los cambios de configuración con aprobación llegan en la Fase 10).
- El límite de tormentas vive en memoria del receptor (se reinicia con él).
- Syslog por UDP no cifra ni autentica; en producción se recomienda TLS (RFC 5425) donde el equipo lo soporte.

## Documentación

- [Requisitos, objetivos y alcance](docs/01_requisitos.md)
- [Historias de usuario](docs/02_historias_usuario.md)
- [Arquitectura y modelo de datos](docs/03_arquitectura.md)
- [Política de defensa frente a agentes de IA](docs/04_politica_ia.md)
- [Bitácora de desarrollo](docs/bitacora.md)
- [Registro de cambios](CHANGELOG.md)
