# Bitácora de desarrollo — NOC Syslog Inteligente

Registro cronológico del trabajo realizado, los problemas encontrados, su causa y la
solución aplicada. Sirve como evidencia de trazabilidad y alimenta la sección
"8. Desarrollo — mejoras realizadas" del informe.

- **Estudiante:** Erick (GitHub: Erick12-hub)
- **Repositorio:** https://github.com/Erick12-hub/noc-syslog-inteligente
- **Entorno:** Windows 11 · Anaconda Prompt · Python 3.14.7 · Git 2.55.0 · Flask 3.1.3

---

## Fase 1 — Estructura, entorno, modelo de datos y repositorio

**Fechas:** 2026-10-02 a 2026-10-05 · **Estado:** ✅ Cerrada

### Qué se realizó

| # | Actividad | Resultado |
|---|---|---|
| 1 | Análisis de la guía del docente y del Prompt maestro | Plan de 6 fases; ajustes: módulo de auditoría, tag v0.1.0, rama `develop`, documentos de diseño |
| 2 | Decisión de stack: Flask + SQLite + HTML/CSS/JS | Flask no requiere compilar dependencias (instalación confiable en Python 3.14) |
| 3 | Estructura del proyecto (`app/`, `docs/`, `data/`) | Organización modular |
| 4 | Entorno virtual `.venv` e instalación de dependencias | Flask 3.1.3, python-dotenv 1.2.4, pytest 9.1.1 |
| 5 | Configuración por variables de entorno (`.env` / `.env.example`) | Sin secretos en el código |
| 6 | Modelo de datos SQLite con 7 tablas | `devices`, `syslog_events`, `severities`, `incidents`, `incident_notes`, `action_proposals`, `audit_log` |
| 7 | Carga de 6 equipos SIMULADOS (Cisco, Fortinet, Huawei, Otro) | IP de documentación RFC 5737, prefijo `SIM-` |
| 8 | Endpoint de salud `/api/health` | `{"status":"ok","tables":7,"version":"0.1.0-dev"}` |
| 9 | Documentos de diseño | Requisitos (14 RF, 7 RNF), 7 historias de usuario, diagramas de arquitectura, flujo seguro y modelo ER |
| 10 | Repositorio Git con ramas `main` y `develop`, publicado en GitHub (público) | 4 commits progresivos |
| 11 | Guía de comandos comentada (`docs/guia_fase1_comandos.txt`) | Referencia para la sustentación |

### Historial de commits

| Hash | Rama | Mensaje |
|---|---|---|
| `c578443` | main | chore: inicializar repositorio |
| `65b1f42` | develop | chore: estructura inicial, dependencias y gitignore |
| `fb0dc81` | develop | feat(db): modelo de datos SQLite, auditoria y equipos simulados |
| `885c27c` | develop | docs: requisitos, historias de usuario, arquitectura y bitacora |

### Evidencias de la Fase 1 (`docs/evidencias/`)

| Archivo | Qué muestra | Evidencia del informe |
|---|---|---|
| `F1-01_instalacion_y_check-db.png` | Instalación de dependencias y 7 tablas creadas | Sección 8, Desarrollo |
| `F1-02_api_health.png` | Aplicación respondiendo en `/api/health` | Sección 8, Desarrollo |
| `F1-03_git_status.png` | `.gitignore` excluye `.env`, `.venv` y `noc.db` | Sección 10/13, Seguridad y control de versiones |
| `F1-04_commit3_docs_y_push.png` | Commit 3 y publicación de la rama `develop` | E02 |
| `F1-05_git_log_historial.png` | Historial: 4 commits y ramas `main`/`develop` | E02 |
| *(pendiente)* | Perfil y repositorio en GitHub | E01 |
| *(pendiente)* | `docs/03_arquitectura.md` con los diagramas en GitHub | E03 |

---

## Registro de problemas y soluciones

| Fecha | Fase | Problema | Causa | Solución |
|---|---|---|---|---|
| 2026-10-02 | 1 | `python` no se reconoce en PowerShell | Python está instalado mediante Anaconda y no está en el PATH de PowerShell | Trabajar siempre desde Anaconda Prompt |
| 2026-10-02 | 1 | `pip.exe` bloqueado por "directiva de Device Guard" | Windows Defender Application Control solo permite ejecutables firmados; el `pip.exe` del entorno virtual no tiene firma | Ejecutar `python -m pip`, que usa el `python.exe` firmado. Es el mismo principio de **lista permitida** que el proyecto aplica a la consola |
| 2026-10-02 | 1 | `requirements.txt` no encontrado | Los archivos aún no estaban copiados en la raíz del repositorio | Copiar el contenido del paquete a la raíz y comprobar con `dir /a` |
| 2026-10-05 | 1 | Versiones de dependencias con rangos (`>=`) | Cada instalación podía traer versiones distintas | Fijar las versiones probadas (`==`): reproducibilidad |
| 2026-10-05 | 1 | Ruta de la BD relativa (`data\noc.db`) | `DATABASE_PATH` en `.env` es relativa a la carpeta desde donde se ejecuta | **Pendiente Fase 2:** resolverla desde la raíz del proyecto |
| 2026-10-05 | 1 | GitHub Desktop: "This directory does not appear to be a Git repository" | El repositorio, creado con Git 2.55, no fue reconocido por GitHub Desktop (probablemente usa una versión interna de Git más antigua) | Publicar por consola: `git remote add origin` + `git push -u`. Verificado con `git rev-parse --show-toplevel` |
| 2026-10-05 | 1 | Inicio de sesión en GitHub al hacer el primer `push` | Primera conexión del equipo con la cuenta | Autorización con Git Credential Manager (OAuth en el navegador). La credencial queda en el Administrador de credenciales de Windows, no en el proyecto |
| 2026-10-05 | 1 | `error: pathspec 'commit' did not match any file(s)` | El comando se pegó dos veces en la misma línea | Ejecutar un comando a la vez |
| 2026-10-05 | 1 | Avisos `LF will be replaced by CRLF` | Windows (CRLF) y Linux (LF) terminan las líneas de forma distinta; Git las convierte | No es un error. **Pendiente Fase 2:** agregar `.gitattributes` |
| 2026-10-05 | 1 | Captura guardada como `F1-02_api_health.png.png` | Windows oculta las extensiones y se agregó otra al guardar | Renombrar con `git mv` en un commit de corrección |
| 2026-10-05 | 2 | Archivo de muestra con PRI `<185>` (severidad 1) en un mensaje Cisco de severidad 5 | Error al escribir el ejemplo | Se corrigió el ejemplo y se agregó la marca `severidad_inconsistente` para detectar este caso en mensajes reales |
| 2026-10-05 | 2 | Prueba `test_caracteres_de_control_se_eliminan` falló: los saltos de línea no se eliminaban | La expresión regular excluía `\x0a` (salto de línea) | Se amplió el rango a `[\x00-\x08\x0a-\x1f\x7f]`. Evita *log injection* (líneas falsas dentro de un mensaje) |
| 2026-10-05 | 2 | El simulador por UDP no puede usar la IP de cada equipo | Desde un PC no se puede falsificar la IP de origen de un paquete | Dos modos: `udp` (origen real 127.0.0.1 = `SIM-GEN-LOCAL`) y `directo` (IP de cada equipo simulado) |
| 2026-10-06 | 2 | Dos capturas con el nombre `web_eventos` | Se tomaron antes y después de importar | `F2-02` renombrada a `F2-02_web_eventos_recibidos_udp.png` |
| 2026-10-06 | 2 | Tras publicar v0.1.0 la consola quedó en `main` | Faltaba volver a la rama de trabajo | `git switch develop` |
| 2026-10-06 | 3 | El detalle de un incidente no se abría al cambiar solo el `#` de la dirección | Cambiar el `#` no recarga la página, así que el código de arranque no volvía a ejecutarse | Se agregó un detector del evento `hashchange` |
| 2026-10-06 | 3 | Títulos poco legibles en incidentes de Fortinet (`logid=0100032002 en ...`) | El código de Fortinet es un número de log, no un nombre | Se presenta como `FortiOS logid 0100032002 en ...` |

---

## Lecciones aprendidas en la Fase 1

1. **Lista permitida como control de seguridad:** Device Guard bloqueó un ejecutable no firmado. Es el mismo principio que aplicará el NOC: lo que no está autorizado explícitamente se bloquea.
2. **El `.gitignore` es un control de seguridad**, no solo de orden: `git status` demostró que `.env` (secretos) y `noc.db` (datos) nunca llegan a GitHub.
3. **Datos simulados identificables:** el prefijo `SIM-`, `is_simulated = 1` y las IP RFC 5737 garantizan que ningún dato de prueba se confunda con uno real.
4. **Historial progresivo:** separar los commits por tipo (`chore`, `feat`, `docs`) hace el historial legible y verificable.
5. **Verificar antes de confirmar:** `git status` antes de cada commit evitó subir archivos equivocados.

---

## Fase 2 — Inventario y motor Syslog

**Fechas:** 2026-10-05 a 2026-10-06 · **Estado:** ✅ Cerrada · publicada como **v0.1.0** (commit `d7ea1a4`)

### Qué se realizó

| # | Actividad | Archivo(s) | Requisito |
|---|---|---|---|
| 1 | Ruta de la BD resuelta desde la raíz del proyecto (hallazgo de la Fase 1) | `app/config.py` | RNF-04 |
| 2 | Normalización de finales de línea (avisos LF/CRLF) | `.gitattributes` | RNF-05 |
| 3 | Migración de esquema sin perder datos (columnas `mnemonic` y `flags`) | `app/db.py`, `app/schema.sql` | RNF-05 |
| 4 | Parser RFC 3164 / RFC 5424 y formatos Cisco IOS, FortiOS (clave=valor) y Huawei VRP | `app/syslog_parser.py` | RF-03 |
| 5 | Ingesta: asociación por IP, lista permitida, deduplicación (60 s), auditoría de sospechosos | `app/ingest.py` | RF-04, RF-11, RF-12, RF-14 |
| 6 | Detección heurística de prompt injection (marca, no bloquea) | `app/security.py` | RNF-02 |
| 7 | API CRUD del inventario con validación (IP, marca, estado, nombre) | `app/devices.py` | RF-01 |
| 8 | API de eventos con filtros e importación de archivos | `app/events.py` | RF-02, RF-06 |
| 9 | Páginas web de inventario y eventos (texto seguro con `textContent`) | `app/templates/`, `app/static/` | RF-01, RF-06 |
| 10 | Receptor Syslog UDP (127.0.0.1:5514) | `app/receiver.py`, `manage.py` | RF-02 |
| 11 | Simulador con 6 escenarios (normal, caída, fuerza bruta, cambio de configuración, inyección, no autorizado) | `scripts/simulador.py` | RF-02 |
| 12 | Archivos de log de ejemplo por fabricante | `samples/` | RF-02 |
| 13 | 31 pruebas automáticas (parser, ingesta, API) | `tests/` | RNF-05 |
| 14 | Equipo `SIM-GEN-LOCAL` (127.0.0.1) como fuente autorizada del simulador | `app/seed.py` | — |

### Decisiones de diseño de la Fase 2

- **La IP de origen se toma del paquete UDP, no del texto del mensaje.** El hostname que trae el
  log lo puede escribir cualquiera; confiar en él permitiría suplantar equipos.
- **La severidad del PRI manda.** Si la severidad del fabricante (`%LINK-3-...`) no coincide con la
  del PRI, se marca `severidad_inconsistente` (posible mensaje alterado o equipo mal configurado).
- **Los eventos de un equipo eliminado se conservan** (`device_id = NULL`) para no perder trazabilidad.
- **La detección de prompt injection solo marca.** Es heurística; la decisión la toma un humano.

### Resultados de la prueba en vivo (2026-10-06)

| Prueba | Resultado |
|---|---|
| `python -m pytest -v` | **31 passed** en Windows / Python 3.14.7 |
| Simulador por UDP (todos los escenarios) | 18 mensajes → **13 eventos** (6 intentos de fuerza bruta agrupados en 1 con `x6`) |
| Clasificación | Cisco, Fortinet y Huawei detectados; severidades 1 a 6 calculadas del PRI |
| Prompt injection | Evento #13 marcado `posible_prompt_injection`, guardado como dato, **no ejecutado** |
| Suplantación | Mensajes que decían venir de otros equipos se asociaron a la IP real (`SIM-GEN-LOCAL`) |
| IP no autorizada (modo directo) | Evento #14 (sev. 0) marcado `equipo_desconocido, fuente_no_autorizada` y auditado |
| Importación de 3 archivos | 20 eventos nuevos, 1 duplicado agrupado, 6 comentarios ignorados |
| **Total en la base** | **34 eventos** |

### Historial de commits de la Fase 2

| Hash | Rama | Mensaje |
|---|---|---|
| `f7845a2` | develop | docs: documento de proceso completo y guia de comandos de la fase 1 |
| `1cab10e` | develop | fix: ruta absoluta de la base de datos y normalizacion de finales de linea |
| `ab00e7d` | develop | feat(syslog): parser multivendor, ingesta, lista permitida, deduplicacion y deteccion de prompt injection |
| `744966a` | develop | feat(web): API e interfaz de inventario y eventos con filtros |
| `70d17e1` | develop | feat(receptor): receptor UDP, importacion de logs y simulador con escenarios |
| `85a00a3` | develop | test: 31 pruebas de parser, ingesta y API |
| `1f3fc03` | develop | docs: README v0.1.0, bitacora y evidencias de la fase 2 |
| `d7ea1a4` | **main** | release: v0.1.0 alfa - inventario y motor Syslog · **tag `v0.1.0`** |

### Evidencias de la Fase 2 (`docs/evidencias/`)

| Archivo | Qué muestra | Evidencia del informe |
|---|---|---|
| `F2-01_pruebas_31_passed.png` | 31 pruebas en verde | E12 |
| `F2-02_web_eventos_recibidos_udp.png` | Eventos recibidos por UDP | E06 |
| `F2-03_consola_eventos.png` | Receptor: deduplicación e inyección | E06 |
| `F2-05_web_inventario.png` | Inventario | E04 |
| `F2-06_web_inventario_crear_editar.png` | Crear y editar equipo | E04 |
| `F2-07_web_validacion_ip.png` | Rechazo de IP inválida | E04 |
| `F2-08_web_eventos.png` | Eventos después de importar | E06 |
| `F2-09_web_filtro_severidad.png` | Filtro por severidad | E07 |
| `F2-10_web_prompt_injection.png` | Evento con prompt injection | E11 |
| `F2-11_consola_no_autorizado_e_importacion.png` | Fuente no autorizada e importación | E06 |
| `F2-12_web_fuente_no_autorizada.png` | Detalle de la IP no autorizada | E11 |
| `F2-13_consola_git_log_v010.png` | Historial y etiqueta v0.1.0 | E02 |

### Pregunta de validación de la Fase 2

> ¿Por qué la deduplicación es un control de seguridad y no solo una forma de ahorrar espacio?

**Respuesta del estudiante:** "La deduplicación es un control ya que con esto puedo mirar si están
entrando de forma simultánea y camuflando una entrada correcta."
**Complemento:** evita que el ruido esconda el evento real, protege al NOC de una inundación que
llene la base (denegación de servicio) y el contador revela patrones como la fuerza bruta.
Limitación: si cada mensaje varía no se agrupan → límite de frecuencia por fuente en la Fase 4.

### Lecciones aprendidas en la Fase 2

1. **Las pruebas encuentran errores de seguridad reales:** la prueba de caracteres de control detectó
   que los saltos de línea no se eliminaban (riesgo de *log injection*) antes de publicar.
2. **Nunca confiar en lo que dice el mensaje:** la identidad de la fuente sale de la IP del paquete.
3. **UDP no confirma la entrega:** que el simulador diga "enviado" no prueba la recepción; la prueba
   está en el receptor.
4. **Migrar, no borrar:** las columnas nuevas se agregaron con `ALTER TABLE` conservando los datos.
5. **Publicar con trazabilidad:** `merge --no-ff` + `tag -a` dejan la versión identificable en el historial.

Documento detallado: [`docs/FASE2_proceso_completo.txt`](FASE2_proceso_completo.txt)

---

## Fase 3 — Dashboard e incidentes

**Fecha:** 2026-10-06 / 07 · **Estado:** ✅ Cerrada (47 pruebas pasan en Windows; 4 commits publicados en `develop`, `7af2c3f..672dbbe`)

### Qué se realizó

| # | Actividad | Archivo(s) | Requisito |
|---|---|---|---|
| 1 | API de resumen: equipos por estado, eventos y críticos 24 h, alertas de seguridad, eventos por severidad y por hora | `app/dashboard.py` | RF-05 |
| 2 | Dashboard como página de inicio, con actualización automática cada 15 s | `app/templates/dashboard.html`, `app/static/dashboard.js` | RF-05 |
| 3 | Incidentes automáticos: severidad 0–3 (política de la tabla `severities`) **y** fuente autorizada | `app/incidents.py`, `app/ingest.py` | RF-08 |
| 4 | Correlación: mismo equipo + mismo código de evento → se suma al incidente abierto (`event_count`) | `app/incidents.py` | RF-12 |
| 5 | Ciclo de vida con transiciones validadas (máquina de estados); cerrar exige resolución; cerrado = inmutable | `app/incidents.py` | RF-07 |
| 6 | Seguimiento con notas automáticas y manuales (autor + fecha) | `app/incidents.py` | RF-07 |
| 7 | Página de incidentes (pestañas, detalle, acciones) y botón "Crear incidente" desde un evento | `app/templates/incidentes.html`, `app/static/incidentes.js`, `app/static/eventos.js` | RF-07 |
| 8 | Migración: columnas `correlation_key`, `event_count`, `last_event_at` en `incidents` | `app/schema.sql`, `app/db.py` | RNF-05 |
| 9 | 16 pruebas nuevas (47 en total) | `tests/test_incidents.py` | RNF-05 |

### Decisiones de diseño de la Fase 3

- **Una fuente no autorizada nunca crea incidentes.** Así un atacante no puede inundar al equipo
  con incidentes falsos (en la prueba, la "emergencia" de 203.0.113.200 no abrió ninguno).
- **El título del incidente lo genera el sistema** a partir de datos estructurados (código y equipo).
  El texto del log no se copia: un log con *prompt injection* produce el título neutro
  "Posible prompt injection en log de ...".
- **Correlación por equipo + código** y no por texto: tres caídas de interfaces distintas del mismo
  router son un solo problema en curso, no tres.
- **Un incidente cerrado no se modifica**: es un registro histórico para la auditoría.
- **Las reglas se validan en el servidor**, no solo en la interfaz: aunque alguien llame a la API
  directamente, no puede cerrar sin resolución ni saltarse estados.

---

### Evidencias de la Fase 3 (`docs/evidencias/`)

Capturas F3-01 a F3-08 (pruebas, dashboard, incidentes, correlación y ciclo de vida), guardadas en
`docs/evidencias/` y publicadas en el último commit de la Fase 3.

Documento detallado: [`docs/FASE3_proceso_completo.txt`](FASE3_proceso_completo.txt)

---

## Fase 4 — Seguridad y defensa ante agentes de IA

**Fecha:** 2026-10-07 / 08 · **Estado:** 🔄 En curso (paquete entregado, pendiente de verificar en el equipo del estudiante)

### Qué se realizó

| # | Actividad | Archivo(s) | Requisito |
|---|---|---|---|
| 1 | Generador de configuraciones Syslog comentadas (7 secciones: NTP, marca de tiempo, servidor, severidad, interfaz de origen, registro de accesos y cambios, verificación) para Cisco, Fortinet y Huawei, con validación de IP, puerto e interfaz | `app/configgen.py`, `configuraciones.html/js` | RF-09 (E09) |
| 2 | Consola simulada de solo lectura: lista permitida por fabricante, bloqueo por defecto, comandos peligrosos, metacaracteres; el actor "asistente de IA" nunca ejecuta | `app/console.py`, `consola.html/js` | RF-10 (E10) |
| 3 | Reglas de detección: `fuerza_bruta`, `cambio_fuera_de_horario`, `cuenta_servicio`, `logs_deshabilitados` (crean o correlacionan incidentes) | `app/rules.py`, `app/ingest.py` | RF-11 |
| 4 | Control de tormentas: `RateLimiter` 100 msg/min por fuente (solo UDP); el exceso se descarta, se audita y abre incidente | `app/security.py`, `app/ingest.py`, `scripts/simulador.py` | RF-12 |
| 5 | Propuestas del asistente: catálogo cerrado, parámetros validados, revisión humana con comentario, aprobación, ejecución simulada, verificación, auditoría | `app/proposals.py`, `incidentes.html/js` | RF-13 (E11) |
| 6 | Página de auditoría con filtros (actor, resultado, texto) | `app/audit_api.py`, `auditoria.html/js` | RF-13 |
| 7 | Política de defensa frente a agentes de IA (amenazas, principios, 11 controles de la guía, flujo, reglas, evidencia) | `docs/04_politica_ia.md` | E11 |
| 8 | 29 pruebas nuevas (76 en total) | `tests/test_seguridad.py` | RNF-05 |

### Decisiones de diseño de la Fase 4

- **Los agentes de IA proponen, los humanos deciden.** El actor `asistente_ia` recibe 403 al ejecutar
  en la consola y al aprobar; ejecutar una propuesta no aprobada devuelve 409. Todo intento queda auditado.
- **Catálogo cerrado:** el asistente no redacta comandos libres a partir del log; elige una acción
  predefinida y solo toma del log parámetros validados (IP con `ipaddress`, interfaz con expresión regular).
- **Si el log tenía *prompt injection*, solo se propone escalar a seguridad.**
- **Denegar por defecto** en la consola: lo que no está en la lista permitida se bloquea.
- **La tormenta se limita solo por UDP:** la importación de archivos la hace un operador a propósito.
- **Los comandos `display` que Huawei registra no cuentan como cambios** (evita falsos positivos).

### Resultados de la prueba en vivo (laboratorio, 2026-10-08)

- `escenario todos`: la regla `fuerza_bruta` abrió el incidente al quinto fallo (contando duplicados x5)
  y propuso bloquear 203.0.113.200; `svc_backup` disparó `cuenta_servicio` y `logs_deshabilitados`.
- `escenario tormenta`: 150 mensajes → 100 aceptados, 50 descartados, 1 auditoría `syslog.tormenta`, 1 incidente.
- `cambio_fuera_de_horario` no se dispara en horario laboral (correcto); se demuestra con las pruebas
  automáticas o ajustando `BUSINESS_HOURS` en `.env`.

### Problemas de la Fase 4

| Problema | Causa | Solución |
|---|---|---|
| La tormenta del simulador no superaba el límite | Los 150 mensajes eran iguales salvo números y la huella de deduplicación los agrupaba | Mensajes con palabras distintas (`_word(n)`) |
| La prueba del flujo de propuestas esperaba menos registros de auditoría | El intento bloqueado (ejecutar sin aprobar) también se audita | Se ajustó lo esperado: el bloqueo es parte de la evidencia |
| El estado del limitador pasaba de una prueba a otra | Vive en memoria (objeto global) | Fixture `reset_storm` en `conftest.py` |

---

## Próximos pasos — Fase 5: Calidad y publicación de v0.2.0

| Pendiente | Requisito |
|---|---|
| GitHub Actions: ejecutar `pytest` en cada push y Pull Request | RNF-05 |
| README final y `CHANGELOG.md` | E12 |
| Prueba de instalación desde cero (clonar → instalar → probar) | RNF-04 |
| `APP_VERSION = "0.2.0"`, Pull Request `develop → main`, etiqueta y release v0.2.0 | E12 |

### Calendario restante (entrega: sábado 2026-10-10)

| Día | Fase |
|---|---|
| Jue 8 | Fase 4: aplicar, probar, capturas E09–E11, commits |
| Vie 9 (mañana) | Fase 5: CI, README, CHANGELOG, PR → v0.2.0 |
| Vie 9 (tarde) | Fase 6: informe PDF con capturas E01–E12 |
| Sáb 10 | Revisión final y entrega |
