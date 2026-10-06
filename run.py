"""
Punto de entrada de la aplicación web.

Uso:  python run.py   ->  http://127.0.0.1:5000
Solo escucha en 127.0.0.1 (el propio equipo); no queda expuesta a la red.
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
