"""
Punto de entrada para OPERACIÓN (Fase 7.5): servidor WSGI waitress.

    python serve.py   ->  http://127.0.0.1:5000

¿Por qué no "python run.py"? El servidor incluido en Flask (Werkzeug) es solo
para DESARROLLO: el propio Flask advierte "Do not use it in a production
deployment", y en modo depuración expone una consola que ejecuta código.
(Corrección Fase 9.2: antes decía que "atiende de a una petición"; no es así,
desde Flask 1.0 también atiende varias a la vez.)
waitress es un servidor WSGI de producción:
  - NUNCA activa el modo depuración, aunque .env diga FLASK_DEBUG=1,
  - número de hilos controlado (WEB_THREADS) y no anuncia su versión,
  - es Python puro: funciona en Windows sin compilar nada.
Se usa en las pruebas en vivo, el laboratorio, la marcha blanca y la sustentación.

WSGI = la interfaz estándar entre un servidor web y una aplicación Python.
Flask es la aplicación; waitress es el servidor que la publica.
"""
import logging

from waitress import serve

from app import APP_VERSION, create_app
from app.config import Config

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    app = create_app()
    app.debug = False          # garantía: en este modo jamás se activa la depuración
    print(f"[NOC] NOC Syslog Inteligente v{APP_VERSION} (waitress, sin depuración)")
    print(f"[NOC] http://{Config.WEB_HOST}:{Config.WEB_PORT}  ·  {Config.WEB_THREADS} hilos  ·  Ctrl+C para detener")
    serve(app, host=Config.WEB_HOST, port=Config.WEB_PORT, threads=Config.WEB_THREADS,
          ident="NOC-Syslog")   # no anunciar "waitress x.y" en el encabezado Server
