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
    updated_at   TEXT NOT NULL
);

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
    is_simulated      INTEGER NOT NULL DEFAULT 0 CHECK (is_simulated IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_events_received ON syslog_events(received_at);
CREATE INDEX IF NOT EXISTS idx_events_severity ON syslog_events(severity);
CREATE INDEX IF NOT EXISTS idx_events_device   ON syslog_events(device_id);
CREATE INDEX IF NOT EXISTS idx_events_fp       ON syslog_events(fingerprint);

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
    last_event_at   TEXT
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
    result    TEXT NOT NULL DEFAULT 'ok' -- ok | bloqueado | error
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
