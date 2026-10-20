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
    # Fase 7.5: servidor web. 127.0.0.1 = solo este equipo (no queda expuesto a la red).
    WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
    WEB_PORT = int(os.getenv("WEB_PORT", "5000"))
    WEB_THREADS = int(os.getenv("WEB_THREADS", "4"))
    # Modo depuración: APAGADO por defecto. Con debug=True, una página de error
    # muestra el código fuente y permite ejecutar Python en el navegador (consola
    # de Werkzeug): nunca debe estar activo fuera del desarrollo.
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

    SYSLOG_HOST = os.getenv("SYSLOG_HOST", "127.0.0.1")
    SYSLOG_PORT = int(os.getenv("SYSLOG_PORT", "5514"))

    # --- Fase 8: inicio de sesión ------------------------------------------
    MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))   # intentos antes de bloquear
    LOCKOUT_MINUTES = int(os.getenv("LOCKOUT_MINUTES", "15"))        # duración del bloqueo
    SESSION_HOURS = int(os.getenv("SESSION_HOURS", "8"))             # una sesión dura un turno
    PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "10"))
    # Cookie de sesión: JavaScript no la puede leer (HttpOnly) y el navegador no
    # la envía desde otros sitios (SameSite). SECURE=1 solo cuando haya HTTPS.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
    SESSION_COOKIE_NAME = "noc_sesion"

    # Nombre del operador por defecto: solo para acciones SIN sesión web
    # (consola de comandos manage.py y receptor UDP). En la web se usa el usuario.
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
    # Fase 7: segundos de tolerancia antes de marcar un evento con 'fecha_futura'.
    # Cubre la latencia de red y pequeñas diferencias de reloj.
    FUTURE_TOLERANCE_SECONDS = int(os.getenv("FUTURE_TOLERANCE_SECONDS", "120"))
    # Prefijos de cuentas de servicio: no deberían cambiar configuraciones.
    SERVICE_ACCOUNT_PREFIXES = tuple(
        p.strip() for p in os.getenv("SERVICE_ACCOUNT_PREFIXES", "svc_").split(",") if p.strip())

    # --- Fase 9: conexión con los equipos (app/connector.py) ----------------
    # Modo "ssh" (equipos fijos): el usuario y la contraseña SOLO viven en .env.
    # Modo "consola" (equipos prestados): cable de consola, sin contraseñas.
    SSH_USERNAME = os.getenv("SSH_USERNAME", "")
    SSH_PASSWORD = os.getenv("SSH_PASSWORD", "")
    SSH_PORT = int(os.getenv("SSH_PORT", "22"))
    CONSOLE_BAUDRATE = int(os.getenv("CONSOLE_BAUDRATE", "9600"))
    CONNECT_TIMEOUT = int(os.getenv("CONNECT_TIMEOUT", "15"))     # segundos para conectar
    COMMAND_TIMEOUT = int(os.getenv("COMMAND_TIMEOUT", "30"))     # segundos por comando
