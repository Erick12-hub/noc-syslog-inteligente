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

    # Ruta del archivo SQLite
    DATABASE_PATH = Path(os.getenv("DATABASE_PATH", BASE_DIR / "data" / "noc.db"))

    # Receptor Syslog UDP. Se usa 5514 porque el puerto estándar 514
    # requiere permisos de administrador.
    SYSLOG_HOST = os.getenv("SYSLOG_HOST", "127.0.0.1")
    SYSLOG_PORT = int(os.getenv("SYSLOG_PORT", "5514"))

    # Nombre del operador por defecto (para auditoría en el MVP sin login)
    DEFAULT_OPERATOR = os.getenv("DEFAULT_OPERATOR", "operador_noc")
