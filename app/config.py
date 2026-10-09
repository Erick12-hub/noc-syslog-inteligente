"""
Configuración de la aplicación.

Los valores se leen de variables de entorno (archivo .env, que NUNCA se sube
a GitHub). Si una variable no existe se usa un valor por defecto seguro para
desarrollo local. Ver .env.example.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Carpeta raíz del proyecto (un nivel arriba de /app)
BASE_DIR = Path(__file__).resolve().parent.parent

# Carga .env si existe (no falla si no está)
load_dotenv(BASE_DIR / ".env")


class Config:
    # Clave para sesiones de Flask. En desarrollo se genera una aleatoria
    # si no se define; nunca se escribe una clave fija en el código.
    SECRET_KEY = os.getenv("SECRET_KEY") or os.urandom(32).hex()

    # Ruta del archivo SQLite.
    # CORRECCIÓN FASE 2: si la ruta del .env es relativa ("data/noc.db"), se
    # resuelve desde la raíz del proyecto (BASE_DIR) y no desde la carpeta
    # donde se ejecuta el comando. Así siempre se usa la MISMA base de datos.
    _db_path = Path(os.getenv("DATABASE_PATH", "data/noc.db"))
    DATABASE_PATH = _db_path if _db_path.is_absolute() else BASE_DIR / _db_path

    # Tamaño máximo de archivo que se puede subir (importación de logs): 2 MB.
    # Evita que un archivo gigante sature la memoria del servidor.
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024

    # Receptor Syslog UDP. Se usa 5514 porque el puerto estándar 514
    # requiere permisos de administrador.
    SYSLOG_HOST = os.getenv("SYSLOG_HOST", "127.0.0.1")
    SYSLOG_PORT = int(os.getenv("SYSLOG_PORT", "5514"))

    # Nombre del operador por defecto (para auditoría en el MVP sin login)
    DEFAULT_OPERATOR = os.getenv("DEFAULT_OPERATOR", "operador_noc")

    # --- Fase 4: política de defensa (ver docs/04_politica_ia.md) -----------
    # Control de tormentas: máximo de mensajes UDP por minuto desde UNA fuente.
    # Lo que exceda se descarta (y se audita) para proteger al NOC.
    STORM_MAX_PER_MINUTE = int(os.getenv("STORM_MAX_PER_MINUTE", "100"))
    # Horario laboral "HH-HH" (hora local). Cambios de configuración fuera de
    # este horario se marcan como sospechosos.
    BUSINESS_HOURS = os.getenv("BUSINESS_HOURS", "07-19")
    # Diferencia de la hora local con UTC (Colombia = -5).
    LOCAL_UTC_OFFSET = int(os.getenv("LOCAL_UTC_OFFSET", "-5"))
    # Prefijos de cuentas de servicio: no deberían cambiar configuraciones.
    SERVICE_ACCOUNT_PREFIXES = tuple(
        p.strip() for p in os.getenv("SERVICE_ACCOUNT_PREFIXES", "svc_").split(",") if p.strip())
