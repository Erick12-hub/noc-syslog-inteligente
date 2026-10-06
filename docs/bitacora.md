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

---

## Lecciones aprendidas en la Fase 1

1. **Lista permitida como control de seguridad:** Device Guard bloqueó un ejecutable no firmado. Es el mismo principio que aplicará el NOC: lo que no está autorizado explícitamente se bloquea.
2. **El `.gitignore` es un control de seguridad**, no solo de orden: `git status` demostró que `.env` (secretos) y `noc.db` (datos) nunca llegan a GitHub.
3. **Datos simulados identificables:** el prefijo `SIM-`, `is_simulated = 1` y las IP RFC 5737 garantizan que ningún dato de prueba se confunda con uno real.
4. **Historial progresivo:** separar los commits por tipo (`chore`, `feat`, `docs`) hace el historial legible y verificable.
5. **Verificar antes de confirmar:** `git status` antes de cada commit evitó subir archivos equivocados.

---

## Fase 2 — Inventario y motor Syslog

**Fechas:** 2026-10-05 a 2026-10-06 · **Estado:** 🔄 En verificación → cierre con tag **v0.1.0**

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

---

## Próximos pasos — Fase 3: Dashboard e incidentes

| Pendiente | Requisito |
|---|---|
| Dashboard: equipos por estado, eventos recientes y críticos, incidentes abiertos | RF-05 (E05) |
| Creación automática de incidentes para severidades 0–3 de fuentes autorizadas | RF-08 |
| Ciclo de vida de incidentes: crear, asignar, seguimiento con notas, cerrar con resolución | RF-07 (E08) |
| Correlación: eventos repetidos del mismo equipo → un solo incidente | RF-12 |

### Calendario restante (entrega: sábado 2026-10-10)

| Día | Fase |
|---|---|
| Lun 5 – Mar 6 | Fase 2: inventario y motor Syslog → v0.1.0 |
| Mar 6 – Mié 7 | Fase 3: dashboard, filtros e incidentes |
| Mié 7 – Jue 8 | Fase 4: configuraciones, consola y política anti-IA |
| Jue 8 | Fase 5: pruebas, CI, README, Pull Request → v0.2.0 |
| Vie 9 | Fase 6: informe PDF con capturas E01–E12 |
| Sáb 10 | Revisión final y entrega |
