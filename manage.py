"""
Utilidades de administración por línea de comandos.

Uso:
    python manage.py init-db                  Crea/actualiza tablas y severidades
    python manage.py init-db --seed           Además carga equipos SIMULADOS
    python manage.py check-db                 Muestra tablas y cantidad de registros
    python manage.py receiver                 Inicia el receptor Syslog UDP
    python manage.py import-log ARCHIVO --ip IP   Importa un archivo de log
"""
import argparse
from pathlib import Path

from app.config import Config
from app.db import connect, init_db
from app.seed import seed_devices


def cmd_init_db(seed: bool):
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    print(f"[OK] Base de datos lista en: {Config.DATABASE_PATH}")
    if seed:
        n = seed_devices(conn)
        print(f"[OK] Equipos simulados insertados: {n}")
    conn.close()


def cmd_check_db():
    conn = connect(Config.DATABASE_PATH)
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    if not tables:
        print("[!] La base de datos está vacía. Ejecute: python manage.py init-db --seed")
    for t in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<18} {count:>5} registros")
    conn.close()


def cmd_import_log(path: str, ip: str):
    from app.ingest import import_lines
    file = Path(path)
    if not file.is_file():
        print(f"[!] No existe el archivo: {file}")
        return
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
    stats = import_lines(conn, lines, ip, Config.DEFAULT_OPERATOR, file.name)
    print(f"[OK] Importación de {file.name} (origen {ip}): {stats}")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Administración NOC Syslog Inteligente")
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init-db", help="Crear/actualizar tablas")
    p_init.add_argument("--seed", action="store_true", help="Cargar equipos simulados")
    sub.add_parser("check-db", help="Ver tablas y registros")
    sub.add_parser("receiver", help="Iniciar receptor Syslog UDP")
    p_imp = sub.add_parser("import-log", help="Importar archivo de log")
    p_imp.add_argument("archivo")
    p_imp.add_argument("--ip", required=True, help="IP del equipo que generó el log")
    args = parser.parse_args()

    if args.command == "init-db":
        cmd_init_db(args.seed)
    elif args.command == "check-db":
        cmd_check_db()
    elif args.command == "receiver":
        from app.receiver import run_receiver
        run_receiver()
    elif args.command == "import-log":
        cmd_import_log(args.archivo, args.ip)
