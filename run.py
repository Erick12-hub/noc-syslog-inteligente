"""
Punto de entrada para DESARROLLO (servidor incluido en Flask).

Uso:  python run.py   ->  http://127.0.0.1:5000
Solo escucha en 127.0.0.1 (el propio equipo); no queda expuesta a la red.

Fase 7.5: el modo depuración ya NO está fijo en True. Se activa solo si el
archivo .env dice FLASK_DEBUG=1. Para operar (marcha blanca) use:
    python serve.py      (servidor waitress, sin depuración)
"""
from app import create_app
from app.config import Config

app = create_app()

if __name__ == "__main__":
    app.run(host=Config.WEB_HOST, port=Config.WEB_PORT, debug=Config.FLASK_DEBUG)
