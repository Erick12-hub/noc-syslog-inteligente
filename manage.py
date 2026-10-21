"""
Utilidades de administración por línea de comandos.

Uso:
    python manage.py init-db                  Crea/actualiza tablas y severidades
    python manage.py init-db --seed           Además carga equipos SIMULADOS
    python manage.py check-db                 Muestra tablas y cantidad de registros
    python manage.py receiver                 Inicia el receptor Syslog UDP
    python manage.py import-log ARCHIVO --ip IP   Importa un archivo de log
    python manage.py create-user USUARIO --rol ROL [--nombre "Nombre"]   (Fase 8)
    python manage.py users                    Lista los usuarios (sin contraseñas)
    python manage.py unlock USUARIO           Desbloquea una cuenta bloqueada
    python manage.py verify-audit             Verifica la cadena de la auditoría (Fase 8.2)
    python manage.py device-session EQUIPO ["comando" ...]   Conecta, identifica y ejecuta (Fase 9.1)
    python manage.py device-sessions EQUIPO   Historial de sesiones del equipo (Fase 9.1)

La contraseña se escribe en la consola SIN mostrarse (getpass) y nunca queda
en el historial de comandos ni en el código. Solo quien tiene acceso al
servidor puede usar estos comandos.
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
    from app.ingest import check_import_vendor, import_lines
    file = Path(path)
    if not file.is_file():
        print(f"[!] No existe el archivo: {file}")
        return
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
    # Fase 7.3: la IP debe ser de un equipo del inventario y la marca debe coincidir
    device = conn.execute("SELECT name, vendor FROM devices WHERE ip = ?", (ip,)).fetchone()
    if device is not None:
        problem = check_import_vendor(lines, device["vendor"])
        if problem:
            from app.db import audit
            audit(conn, Config.DEFAULT_OPERATOR, "syslog.import_rechazado", "devices", None,
                  f"archivo={file.name} origen={ip} {problem}", "bloqueado")
            print(f"[!] Importación RECHAZADA ({device['name']}, {ip}): {problem}")
            conn.close()
            return
    stats = import_lines(conn, lines, ip, Config.DEFAULT_OPERATOR, file.name)
    print(f"[OK] Importación de {file.name} (origen {ip}): {stats}")
    conn.close()


def cmd_create_user(username: str, role: str, full_name: str):
    from getpass import getpass
    from app.auth import create_user
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    password = getpass("Contraseña (no se muestra): ")
    if password != getpass("Repita la contraseña: "):
        print("[!] Las contraseñas no coinciden")
        conn.close()
        return
    try:
        uid = create_user(conn, username, password, role, full_name, actor="consola_servidor")
        print(f"[OK] Usuario '{username.lower()}' creado con rol {role} (id {uid})")
    except ValueError as e:
        for msg in e.args[0]:
            print(f"[!] {msg}")
    conn.close()


def cmd_users():
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    rows = conn.execute("SELECT username, role, active, failed_attempts, locked_until, last_login_at "
                        "FROM users ORDER BY username").fetchall()
    if not rows:
        print("[!] No hay usuarios. Cree el primero con: python manage.py create-user admin --rol admin_seguridad")
    for u in rows:
        state = "activo" if u["active"] else "DESACTIVADO"
        if u["locked_until"]:
            state += f", bloqueado hasta {u['locked_until']}"
        print(f"  {u['username']:<16} {u['role']:<16} {state:<40} último ingreso: {u['last_login_at'] or '-'}")
    conn.close()


def cmd_unlock(username: str):
    from app.db import audit, now_iso
    conn = connect(Config.DATABASE_PATH)
    cur = conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL, updated_at = ? "
                       "WHERE username = ?", (now_iso(), username.lower()))
    conn.commit()
    if cur.rowcount:
        audit(conn, "consola_servidor", "user.unlock", "users", None, f"usuario={username.lower()}")
        print(f"[OK] Cuenta '{username.lower()}' desbloqueada")
    else:
        print(f"[!] No existe el usuario '{username}'")
    conn.close()


def cmd_verify_audit():
    from app.db import verify_audit_chain
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    r = verify_audit_chain(conn)
    if r["ok"]:
        print(f"[OK] Cadena de auditoría ÍNTEGRA: {r['total']} registros")
    else:
        print(f"[!] CADENA ROTA en el registro {r['broken_at']}: {r['reason']}")
    print(f"     Último registro válido: {r['last_id']}  ·  último hash: {r['last_hash']}")
    conn.close()


def cmd_device_session(name: str, commands: list[str]):
    """Fase 9.1: misma sesión que la web (mismas reglas y la misma auditoría)."""
    from app.connector import run_session
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    device = conn.execute("SELECT * FROM devices WHERE name = ?", (name,)).fetchone()
    if device is None:
        print(f"[!] No existe el equipo {name!r} en el inventario")
        return
    print(f"[..] Conectando con {name} (modo {device['connection_mode']})...")
    result, status = run_session(conn, device, commands, Config.DEFAULT_OPERATOR)
    for e in result.get("errors", []):
        print(f"[!] {e}")
    if "id" in result:
        where = result["transport"] + ("" if result["target"] == result["transport"] else f" {result['target']}")
        print(f"[{'OK' if result['status'] == 'cerrada' else '!'}] Sesión {result['id']}: {result['status']} · {where}")
        if result["serial_number"] or result["model"]:
            print(f"     Equipo físico: serie={result['serial_number']}  modelo={result['model']}  "
                  f"versión={result['os_version']}")
        for w in result["warnings"]:
            print(f"[!] {w}")
        for c in result["commands"]:
            print(f"\n--- {c['command']} ({c['duration_ms']} ms, huella {c['output_sha256'][:16]}...) ---")
            print(c["output"] if c["command"] != "show version" else "(identificación: ver arriba)")
    conn.close()


def cmd_device_sessions(name: str):
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    rows = conn.execute("SELECT * FROM device_sessions WHERE device_name = ? ORDER BY id DESC LIMIT 20",
                        (name,)).fetchall()
    if not rows:
        print(f"Sin sesiones registradas para {name}")
    print(f"{'#':>4}  {'Inicio (UTC)':20}  {'Modo':9}  {'Estado':8}  {'Serie':14}  {'Cmds':>4}  Usuario")
    for r in rows:
        print(f"{r['id']:>4}  {r['started_at']:20}  {r['transport']:9}  {r['status']:8}  "
              f"{(r['serial_number'] or '-'):14}  {r['commands_count']:>4}  {r['started_by']}")
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
    p_cu = sub.add_parser("create-user", help="Crear un usuario del NOC (Fase 8)")
    p_cu.add_argument("usuario")
    p_cu.add_argument("--rol", required=True, choices=["operador", "auditor", "admin_seguridad"])
    p_cu.add_argument("--nombre", default="", help="Nombre completo (opcional)")
    sub.add_parser("users", help="Listar usuarios")
    p_un = sub.add_parser("unlock", help="Desbloquear una cuenta")
    p_un.add_argument("usuario")
    sub.add_parser("verify-audit", help="Verificar la cadena de integridad de la auditoría")
    p_ds = sub.add_parser("device-session", help="Conectar con un equipo, identificarlo y ejecutar comandos")
    p_ds.add_argument("equipo")
    p_ds.add_argument("comandos", nargs="*", help='Comandos de solo lectura, entre comillas')
    p_dl = sub.add_parser("device-sessions", help="Historial de sesiones de un equipo")
    p_dl.add_argument("equipo")
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
    elif args.command == "create-user":
        cmd_create_user(args.usuario, args.rol, args.nombre)
    elif args.command == "users":
        cmd_users()
    elif args.command == "unlock":
        cmd_unlock(args.usuario)
    elif args.command == "verify-audit":
        cmd_verify_audit()
    elif args.command == "device-session":
        cmd_device_session(args.equipo, args.comandos)
    elif args.command == "device-sessions":
        cmd_device_sessions(args.equipo)
