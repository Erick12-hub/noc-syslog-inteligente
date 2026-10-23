-- =====================================================================
-- NOC Syslog Inteligente - Modelo de datos (SQLite)
-- Versión: v0.1.0 (base) -> v0.2.0 (MVP)
--
-- Convenciones:
--   * Fechas en formato ISO 8601 UTC (texto), p. ej. 2026-10-02T19:30:00Z
--   * is_simulated = 1 marca TODO dato de prueba (requisito del curso:
--     los datos simulados deben estar claramente identificados).
--   * Las tablas se crean solo si no existen (re-ejecutable sin perder datos).
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- 1. Catálogo de severidades Syslog (RFC 5424, sección 6.2.1)
--    Tabla de referencia: 0 = más grave, 7 = menos grave.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS severities (
    code        INTEGER PRIMARY KEY CHECK (code BETWEEN 0 AND 7),
    keyword     TEXT NOT NULL,          -- emerg, alert, crit, ...
    name        TEXT NOT NULL,          -- Emergency, Alert, ...
    description TEXT NOT NULL,
    creates_incident INTEGER NOT NULL DEFAULT 0  -- política: 1 = genera incidente automático
);

-- ---------------------------------------------------------------------
-- 2. Inventario de dispositivos
--    'authorized' implementa la lista permitida de FUENTES Syslog:
--    solo se confía en eventos cuya IP origen pertenezca a un equipo autorizado.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS devices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    ip           TEXT NOT NULL UNIQUE,
    vendor       TEXT NOT NULL CHECK (vendor IN ('Cisco', 'Fortinet', 'Huawei', 'Otro')),
    model        TEXT,
    version      TEXT,                  -- versión de firmware / sistema operativo
    location     TEXT,
    status       TEXT NOT NULL DEFAULT 'desconocido'
                 CHECK (status IN ('activo', 'alerta', 'caido', 'mantenimiento', 'desconocido')),
    authorized   INTEGER NOT NULL DEFAULT 1 CHECK (authorized IN (0, 1)),
    is_simulated INTEGER NOT NULL DEFAULT 0 CHECK (is_simulated IN (0, 1)),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    -- Fase 9: cómo se conecta el NOC al equipo (ver app/connector.py)
    connection_mode TEXT NOT NULL DEFAULT 'ninguno',  -- ninguno | simulado | consola | ssh
    platform        TEXT,             -- cisco_ios | cisco_xe | fortinet | huawei
    console_port    TEXT,             -- COM3 (Windows) o /dev/ttyUSB0 (Linux), modo consola
    -- Lo que el NOC LEYÓ del equipo en la última identificación
    serial_number   TEXT,             -- identifica al equipo FÍSICO (la IP puede cambiar)
    detected_model  TEXT,
    detected_version TEXT,
    host_key_fp     TEXT,             -- huella de la llave SSH (solo modo ssh, equipos fijos)
    last_identified_at TEXT
);

-- ---------------------------------------------------------------------
-- 2b. Interfaces de cada equipo (Fase 8.4)
--    Lista de las interfaces REALES del equipo. Si un evento menciona una
--    interfaz que el equipo no tiene registrada, se marca 'interfaz_desconocida'
--    (inventario desactualizado o mensaje suplantado).
--    COLLATE NOCASE: 'gigabitethernet0/1' y 'GigabitEthernet0/1' son la misma.
--    ON DELETE CASCADE: si se elimina el equipo, se eliminan sus interfaces.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS interfaces (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    name        TEXT NOT NULL COLLATE NOCASE,   -- ej. GigabitEthernet0/0/1, port1, Vlanif10
    description TEXT,                           -- ej. "Enlace a ISP principal"
    status      TEXT NOT NULL DEFAULT 'desconocido'
                CHECK (status IN ('up', 'down', 'admin_down', 'desconocido')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    -- Fase 9.3: datos leídos del equipo real (show ip interface brief)
    ip_address  TEXT,                           -- IP de la interfaz o NULL (unassigned)
    source      TEXT NOT NULL DEFAULT 'manual', -- manual | equipo
    last_seen_at TEXT,                          -- última vez que el equipo la reportó
    UNIQUE (device_id, name)                    -- un equipo no repite interfaz
);

-- ---------------------------------------------------------------------
-- 2c. Sesiones con los equipos (Fase 9.1): TRAZABILIDAD de cada conexión
--    Una fila por cada vez que el NOC se conecta a un equipo (consola o SSH).
--    serial_number = el equipo FÍSICO que respondió en esa sesión.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS device_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    device_name   TEXT NOT NULL,            -- se conserva aunque se borre el equipo
    transport     TEXT NOT NULL CHECK (transport IN ('simulado', 'consola', 'ssh')),
    target        TEXT NOT NULL,            -- COM3, 192.0.2.1:22 o "simulado"
    started_by    TEXT NOT NULL,            -- usuario del NOC
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    status        TEXT NOT NULL DEFAULT 'abierta'
                  CHECK (status IN ('abierta', 'cerrada', 'fallida')),
    error         TEXT,
    serial_number TEXT,
    model         TEXT,
    os_version    TEXT,
    host_key_fp   TEXT,
    warnings      TEXT,                     -- avisos separados por " | "
    commands_count INTEGER NOT NULL DEFAULT 0,
    is_simulated  INTEGER NOT NULL DEFAULT 0 CHECK (is_simulated IN (0, 1))
);

-- Cada comando enviado en una sesión, con su salida y la huella de la salida
CREATE TABLE IF NOT EXISTS device_commands (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER NOT NULL REFERENCES device_sessions(id) ON DELETE CASCADE,
    command       TEXT NOT NULL,
    requested_by  TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    duration_ms   INTEGER,
    status        TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    output        TEXT,                     -- recortada a 64 KB
    output_sha256 TEXT                      -- huella de la salida COMPLETA
);
CREATE INDEX IF NOT EXISTS idx_sessions_device ON device_sessions(device_id, started_at);
CREATE INDEX IF NOT EXISTS idx_commands_session ON device_commands(session_id);

-- ---------------------------------------------------------------------
-- 2d. Versiones de configuración (Fase 10.1)
--    Una fila por cada configuración DISTINTA leída de un equipo. El texto se
--    guarda normalizado y SIN secretos (app/configversions.py). Son evidencia:
--    los triggers impiden modificar el contenido o borrarlas.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS config_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    device_name   TEXT NOT NULL,            -- se conserva aunque se borre el equipo
    version_no    INTEGER NOT NULL,         -- 1, 2, 3... por equipo
    session_id    INTEGER REFERENCES device_sessions(id) ON DELETE SET NULL,
    captured_by   TEXT NOT NULL,
    captured_at   TEXT NOT NULL,
    serial_number TEXT,                     -- equipo FÍSICO del que se leyó
    command       TEXT NOT NULL,            -- show running-config, display current-configuration...
    sha256        TEXT NOT NULL,            -- huella del texto guardado
    lines         INTEGER NOT NULL,
    masked        INTEGER NOT NULL DEFAULT 0,   -- secretos ocultados
    added         INTEGER,                  -- líneas agregadas respecto a la versión anterior
    removed       INTEGER,                  -- líneas quitadas respecto a la versión anterior
    note          TEXT,
    is_simulated  INTEGER NOT NULL DEFAULT 0 CHECK (is_simulated IN (0, 1)),
    content       TEXT NOT NULL,
    UNIQUE (device_id, version_no)
);
CREATE INDEX IF NOT EXISTS idx_configs_device ON config_versions(device_id, version_no);
-- Solo se protege el contenido: borrar el equipo pone device_id en NULL (permitido)
CREATE TRIGGER IF NOT EXISTS config_no_update
BEFORE UPDATE OF device_name, version_no, captured_by, captured_at, serial_number, command, sha256,
                 lines, masked, added, removed, note, content ON config_versions
BEGIN SELECT RAISE(ABORT, 'Las versiones de configuración son evidencia: no se pueden modificar'); END;
CREATE TRIGGER IF NOT EXISTS config_no_delete BEFORE DELETE ON config_versions
BEGIN SELECT RAISE(ABORT, 'Las versiones de configuración son evidencia: no se pueden borrar'); END;

-- ---------------------------------------------------------------------
-- 3. Eventos Syslog recibidos o importados
--    'raw' guarda el mensaje original TAL CUAL llegó. Se trata como DATO
--    NO CONFIABLE: nunca se interpreta como instrucción ni se ejecuta.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS syslog_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at       TEXT NOT NULL,     -- cuándo lo recibió el NOC
    event_time        TEXT,              -- fecha que trae el propio mensaje (si la trae)
    source_ip         TEXT NOT NULL,
    device_id         INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    vendor            TEXT,              -- copiado del inventario o 'Desconocido'
    facility          INTEGER CHECK (facility BETWEEN 0 AND 23),
    severity          INTEGER NOT NULL CHECK (severity BETWEEN 0 AND 7)
                      REFERENCES severities(code),
    hostname          TEXT,
    app_name          TEXT,
    message           TEXT NOT NULL,
    raw               TEXT NOT NULL,
    origin            TEXT NOT NULL CHECK (origin IN ('udp', 'importacion', 'simulador')),
    authorized_source INTEGER NOT NULL DEFAULT 0 CHECK (authorized_source IN (0, 1)),
    mnemonic          TEXT,              -- código del fabricante (ej. LINK-3-UPDOWN)
    flags             TEXT,              -- alertas de seguridad separadas por coma
    fingerprint       TEXT,              -- huella para deduplicación
    dup_count         INTEGER NOT NULL DEFAULT 1,  -- repeticiones agrupadas
    is_simulated      INTEGER NOT NULL DEFAULT 0 CHECK (is_simulated IN (0, 1)),
    -- Fase 7: puerto e interfaz involucrados (extraídos del mensaje por el parser)
    interface         TEXT,              -- ej. GigabitEthernet0/0/2, port1, wan1
    src_port          INTEGER CHECK (src_port BETWEEN 1 AND 65535),  -- puerto de origen
    dst_port          INTEGER CHECK (dst_port BETWEEN 1 AND 65535),  -- puerto de destino (atacado)
    -- Fase 7: fecha del mensaje convertida a UTC (base del cálculo de desfase NTP)
    event_time_utc    TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_received ON syslog_events(received_at);
CREATE INDEX IF NOT EXISTS idx_events_severity ON syslog_events(severity);
CREATE INDEX IF NOT EXISTS idx_events_device   ON syslog_events(device_id);
-- (Fase 7.4: el índice por huella pasó a ser compuesto; ver INDEXES en app/db.py)

-- ---------------------------------------------------------------------
-- 4. Incidentes (creación, asignación, seguimiento y cierre)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incidents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    description  TEXT,
    severity     INTEGER NOT NULL CHECK (severity BETWEEN 0 AND 7),
    status       TEXT NOT NULL DEFAULT 'abierto'
                 CHECK (status IN ('abierto', 'asignado', 'en_progreso', 'cerrado')),
    assigned_to  TEXT,
    device_id    INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    event_id     INTEGER REFERENCES syslog_events(id) ON DELETE SET NULL,
    resolution   TEXT,                   -- obligatoria al cerrar
    created_by   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    closed_at    TEXT,
    is_simulated INTEGER NOT NULL DEFAULT 0 CHECK (is_simulated IN (0, 1)),
    -- Fase 3: correlación. Eventos del mismo equipo y mismo tipo se suman al
    -- incidente abierto en vez de crear uno nuevo por cada evento.
    correlation_key TEXT,
    event_count     INTEGER NOT NULL DEFAULT 1,
    last_event_at   TEXT,
    -- Fase 7: marcas de tiempo para los indicadores MTTA y MTTR
    assigned_at     TEXT,                -- primera vez que se asignó un responsable
    started_at      TEXT                 -- primera vez que pasó a 'en_progreso'
);

CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);

-- Bitácora de seguimiento de cada incidente
CREATE TABLE IF NOT EXISTS incident_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    author      TEXT NOT NULL,
    note        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- 5. Propuestas de acción (flujo seguro obligatorio)
--    evento -> validación -> PROPUESTA -> revisión humana -> aprobación
--    -> ejecución autorizada -> verificación -> auditoría
--    En el MVP la "ejecución" es simulada; nunca se toca un equipo real.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS action_proposals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id   INTEGER REFERENCES incidents(id) ON DELETE CASCADE,
    proposed_by   TEXT NOT NULL,         -- 'asistente_ia' u operador
    command       TEXT NOT NULL,
    justification TEXT,
    risk          TEXT NOT NULL DEFAULT 'medio' CHECK (risk IN ('bajo', 'medio', 'alto')),
    status        TEXT NOT NULL DEFAULT 'pendiente'
                  CHECK (status IN ('pendiente', 'aprobada', 'rechazada', 'ejecutada', 'verificada')),
    reviewed_by   TEXT,
    reviewed_at   TEXT,
    result        TEXT,
    created_at    TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- 6. Auditoría: quién hizo qué, cuándo y con qué resultado.
--    Solo se inserta; la aplicación nunca actualiza ni borra registros aquí.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    actor     TEXT NOT NULL,             -- operador, 'sistema' o 'asistente_ia'
    action    TEXT NOT NULL,             -- p. ej. device.create, console.blocked
    entity    TEXT,                      -- tabla/objeto afectado
    entity_id INTEGER,
    detail    TEXT,
    result    TEXT NOT NULL DEFAULT 'ok', -- ok | alerta | bloqueado | error
    -- Fase 8.2: cadena de integridad (ver audit() y verify_audit_chain() en app/db.py)
    prev_hash TEXT,                      -- hash del registro anterior
    hash      TEXT                       -- SHA-256(prev_hash + datos de este registro)
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);

-- ---------------------------------------------------------------------
-- 7. Usuarios del NOC (Fase 8)
--    password_hash: SOLO el hash scrypt; la contraseña nunca se guarda.
--    failed_attempts / locked_until: bloqueo tras varios intentos fallidos.
--    No hay usuarios por defecto: el primero se crea con
--    "python manage.py create-user" (contraseña escrita por consola).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    full_name       TEXT,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('operador', 'auditor', 'admin_seguridad')),
    active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,                  -- UTC; NULL = no bloqueada
    last_login_at   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
