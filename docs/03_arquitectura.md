# 3. Diseño de la solución

## 3.1 Arquitectura general

Aplicación monolítica en capas, ejecutada localmente:

```mermaid
flowchart LR
    subgraph Fuentes["Fuentes Syslog (SIMULADAS en el MVP)"]
        CIS[Cisco IOS-XE]
        FTN[FortiGate]
        HUA[Huawei VRP]
        SIMU[simulador.py]
        FILE[Archivo .log]
    end

    subgraph NOC["NOC Syslog Inteligente (127.0.0.1)"]
        RX["Receptor UDP :5514"]
        IMP["Importador de archivos"]
        SEC{"Política de seguridad<br/>· fuentes permitidas<br/>· límite de frecuencia<br/>· deduplicación"}
        PAR["Parser RFC 3164/5424<br/>PRI → facility + severidad"]
        CLS["Clasificador<br/>dispositivo · marca · severidad"]
        INC["Gestor de incidentes"]
        API["API REST Flask"]
        DB[("SQLite<br/>noc.db")]
        AUD["Auditoría"]
        CFG["Generador de configuraciones"]
        CON["Consola simulada<br/>lista de comandos permitidos"]
    end

    UI["Dashboard web<br/>HTML + CSS + JS"]
    OP(("Operador<br/>humano"))

    CIS & FTN & HUA & SIMU -->|UDP| RX
    FILE --> IMP
    RX & IMP --> PAR --> SEC --> CLS --> DB
    CLS -->|sev 0-3 + fuente autorizada| INC --> DB
    API <--> DB
    UI <-->|HTTP/JSON| API
    OP --> UI
    API --> CFG
    API --> CON
    CON & INC & API --> AUD --> DB
```

## 3.2 Flujo seguro de acciones (obligatorio)

Ninguna acción sobre un equipo se ejecuta sin pasar por todos los pasos. Un asistente de IA
solo puede **proponer** acciones; no puede aprobarlas ni ejecutarlas.

```mermaid
flowchart LR
    A[Evento detectado] --> B{Validación<br/>¿fuente autorizada?<br/>¿formato válido?}
    B -- No --> X[Marcar y auditar<br/>sin acción]
    B -- Sí --> C[Propuesta de acción<br/>estado: pendiente]
    C --> D{Revisión humana}
    D -- Rechaza --> R[Rechazada<br/>+ auditoría]
    D -- Aprueba --> E[Ejecución autorizada<br/>solo comandos permitidos]
    E --> F[Verificación<br/>del resultado]
    F --> G[Auditoría<br/>quién · qué · cuándo · resultado]
```

## 3.3 Modelo de datos

```mermaid
erDiagram
    SEVERITIES ||--o{ SYSLOG_EVENTS : clasifica
    DEVICES ||--o{ SYSLOG_EVENTS : genera
    DEVICES ||--o{ INCIDENTS : afecta
    SYSLOG_EVENTS ||--o| INCIDENTS : origina
    INCIDENTS ||--o{ INCIDENT_NOTES : seguimiento
    INCIDENTS ||--o{ ACTION_PROPOSALS : propone

    DEVICES {
        int id PK
        text name UK
        text ip UK
        text vendor "Cisco|Fortinet|Huawei|Otro"
        text model
        text version
        text location
        text status
        int authorized "lista permitida"
        int is_simulated
        text updated_at
    }
    SYSLOG_EVENTS {
        int id PK
        text received_at
        text source_ip
        int device_id FK
        int facility "0-23"
        int severity FK "0-7"
        text message
        text raw "dato NO confiable"
        text origin "udp|importacion|simulador"
        int authorized_source
        text fingerprint "deduplicación"
        int dup_count
    }
    INCIDENTS {
        int id PK
        text title
        int severity
        text status "abierto|asignado|en_progreso|cerrado"
        text assigned_to
        int device_id FK
        int event_id FK
        text resolution
    }
    INCIDENT_NOTES {
        int id PK
        int incident_id FK
        text author
        text note
    }
    ACTION_PROPOSALS {
        int id PK
        int incident_id FK
        text proposed_by
        text command
        text status "pendiente|aprobada|rechazada|ejecutada|verificada"
        text reviewed_by
    }
    AUDIT_LOG {
        int id PK
        text ts
        text actor
        text action
        text result "ok|bloqueado|error"
    }
    SEVERITIES {
        int code PK "0-7"
        text keyword
        int creates_incident
    }
```

## 3.4 Módulos

| Módulo | Archivo(s) | Responsabilidad | Fase |
|---|---|---|---|
| Configuración | `app/config.py`, `.env` | Variables de entorno, sin secretos en el código | 1 |
| Datos | `app/db.py`, `app/schema.sql` | Conexión, esquema y auditoría | 1 |
| Inventario | `app/devices.py` | CRUD de equipos | 2 |
| Syslog | `app/syslog_parser.py`, `app/receiver.py` | Parser, receptor UDP, importación | 2 |
| Seguridad | `app/security.py` | Fuentes permitidas, deduplicación, límite de frecuencia | 2–4 |
| Incidentes | `app/incidents.py` | Ciclo de vida y propuestas de acción | 3 |
| Dashboard | `app/static/`, `app/templates/` | Interfaz web | 3 |
| Configuraciones | `app/configgen.py` | Plantillas Cisco, Fortinet y Huawei | 4 |
| Consola | `app/console.py` | Comandos permitidos y bloqueados | 4 |

## 3.5 Decisiones técnicas

| Decisión | Justificación |
|---|---|
| Flask en lugar de FastAPI | Sin dependencias compiladas; instalación confiable en Windows con Python 3.14; código fácil de explicar |
| SQLite | Viene con Python; un solo archivo; suficiente para el MVP |
| Puerto UDP 5514 | El puerto 514 requiere permisos de administrador; en los equipos se configura el puerto destino |
| Fechas en UTC | Correlación entre equipos de distintas zonas; se complementa con NTP |
| IP RFC 5737 en los datos simulados | Garantiza que no se usen IP reales de producción |
