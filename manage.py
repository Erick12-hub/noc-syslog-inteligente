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
    python manage.py device-interfaces EQUIPO [--eliminar-ausentes]   Lee las interfaces reales (Fase 9.3)
    python manage.py device-diag EQUIPO ping|traceroute DESTINO   Diagnóstico desde el equipo (Fase 9.4)
    python manage.py check-consistency        Reloj, consistencia y cadena de auditoría (Fase 9.5)

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


def cmd_device_interfaces(name: str, remove_missing: bool):
    """Fase 9.3: lee las interfaces del equipo y actualiza el inventario (igual que la web)."""
    from app.connector import run_session
    from app.interfaces import SYNC_COMMAND, apply_sync, parse_interfaces
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    device = conn.execute("SELECT * FROM devices WHERE name = ?", (name,)).fetchone()
    if device is None or SYNC_COMMAND.get(device["platform"]) is None:
        print(f"[!] {name!r} no existe o no tiene plataforma en el inventario")
        return
    command = SYNC_COMMAND[device["platform"]]
    print(f"[..] Leyendo interfaces de {name} ({command})...")
    result, status = run_session(conn, device, [command], Config.DEFAULT_OPERATOR)
    if status != 200:
        for e in result.get("errors", []):
            print(f"[!] {e}")
        return
    output = next(c["output"] for c in result["commands"] if c["command"] == command)
    rows = parse_interfaces(device["platform"], output)
    if not rows:
        print("[!] El equipo respondió, pero no se reconoció ninguna interfaz")
        return
    s = apply_sync(conn, device, rows, Config.DEFAULT_OPERATOR, remove_missing)
    print(f"[OK] Sesión {result['id']} · equipo físico {result['serial_number']}")
    labels = [("nuevas", "Nuevas"), ("actualizadas", "Cambiaron"), ("sin_cambios", "Sin cambios"),
              ("desaparecidas", "Ya no están en el equipo"), ("eliminadas", "Eliminadas del inventario"),
              ("invalidas", "Rechazadas (nombre inválido)")]
    for key, label in labels:
        if s[key]:
            print(f"     {label} ({len(s[key])}): {', '.join(s[key])}")
    conn.close()


def cmd_device_diag(name: str, kind: str, target: str):
    """Fase 9.4: ping o traceroute ejecutado POR el equipo (mismas reglas que la web)."""
    from app.diagnostics import run_diagnostic
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    device = conn.execute("SELECT * FROM devices WHERE name = ?", (name,)).fetchone()
    if device is None:
        print(f"[!] No existe el equipo {name!r} en el inventario")
        return
    print(f"[..] {kind} {target} desde {name} (modo {device['connection_mode']})...")
    result, status = run_diagnostic(conn, device, kind, target, Config.DEFAULT_OPERATOR)
    for e in result.get("errors", []):
        print(f"[!] {e}")
    if status == 200:
        print(f"[OK] Sesión {result['session']} · equipo físico {result['serial_number']}")
        print(f"     {result['summary']}")
        print("\n" + result["output"])
    conn.close()


def cmd_check_consistency():
    """Fase 9.5: la misma revisión que hace el receptor cada N minutos (con efectos)."""
    from app.consistency import run_consistency
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    r = run_consistency(conn, Config.DEFAULT_OPERATOR)
    print("Reloj de los equipos (desfase = recibido - hora del evento):")
    for c in r["clocks"]:
        if c["samples"]:
            print(f"  {c['device']:<16} {c['status']:<8} {c['text']}  ({c['samples']} eventos)")
    c = r["counts"]
    print(f"\nHallazgos -> críticos: {c['critico']} · avisos: {c['aviso']} · informativos: {c['info']}")
    for f in r["findings"]:
        print(f"  [{f['severity'].upper():<7}] {f['device']}: {f['detail']}")
        print(f"            -> {f['suggestion']}")
    print(f"\nCadena de auditoría: {'íntegra' if r['chain']['ok'] else 'ROTA'} ({r['chain']['total']} registros)"
          + (f" · incidente #{r['incident']}" if r["incident"] else ""))
    conn.close()


def cmd_device_config(name: str, note: str):
    """Fase 10.1: lee la configuración del equipo y guarda una versión (secretos ocultos)."""
    from app.configversions import capture_config
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    device = conn.execute("SELECT * FROM devices WHERE name = ?", (name,)).fetchone()
    if device is None:
        print(f"[!] No existe el equipo {name!r} en el inventario")
        return
    print(f"[..] Leyendo la configuración de {name} (modo {device['connection_mode']})...")
    r, status = capture_config(conn, device, Config.DEFAULT_OPERATOR, note)
    for e in r.get("errors", []):
        print(f"[!] {e}")
    if "version" in r:
        v = r["version"]
        print(f"[{'!' if r['changed'] and r['previous'] else 'OK'}] {r['message']}")
        print(f"     v{v['version_no']} · {v['lines']} líneas · {r['masked']} secretos ocultos · "
              f"equipo físico {v['serial_number']} · SHA-256 {v['sha256'][:16]}...")
        for w in r["warnings"]:
            print(f"[!] {w}")
    conn.close()


def cmd_device_configs(name: str):
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    rows = conn.execute("SELECT * FROM config_versions WHERE device_name = ? ORDER BY version_no DESC",
                        (name,)).fetchall()
    if not rows:
        print(f"Sin versiones de configuración para {name}")
    print(f"{'ID':>4}  {'Ver':>4}  {'Fecha (UTC)':20}  {'Líneas':>6}  {'Cambios':>9}  {'Serie':14}  Usuario · nota")
    for r in rows:
        ch = f"+{r['added']} -{r['removed']}" if r["added"] is not None else "inicial"
        print(f"{r['id']:>4}  v{r['version_no']:<3}  {r['captured_at']:20}  {r['lines']:>6}  {ch:>9}  "
              f"{(r['serial_number'] or '-'):14}  {r['captured_by']}" + (f" · {r['note']}" if r["note"] else ""))
    conn.close()


def cmd_config_diff(id_a: int, id_b: int):
    from app.configversions import compare
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    r, status = compare(conn, id_a, id_b)
    for e in r.get("errors", []):
        print(f"[!] {e}")
    if status == 200:
        for w in r["warnings"]:
            print(f"[!] {w}")
        if r["identical"]:
            print("[OK] Las dos versiones son idénticas")
        else:
            print(f"[..] +{r['added']} líneas agregadas · -{r['removed']} quitadas\n")
            print("\n".join(r["lines"]))
    conn.close()


def cmd_metrics(days: int, origin: str):
    """Fase 10.4: indicadores de operación (MTTA, MTTR, SLA y cambios)."""
    from app.metrics import compute
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    m = compute(conn, days, origin)
    period = f"últimos {days} días" if days else "todo el historial"
    print(f"Indicadores del NOC · {period} · incidentes {origin} ({m['incidents']})\n")
    print(f"  MTTA (tiempo hasta atender) : promedio {m['mtta']['mean']:<10} mediana {m['mtta']['median']:<10} "
          f"({m['mtta']['n']} atendidos) · dentro del objetivo: {m['ack_sla_pct'] if m['ack_sla_pct'] is not None else '—'} %")
    print(f"  MTTR (tiempo hasta resolver): promedio {m['mttr']['mean']:<10} mediana {m['mttr']['median']:<10} "
          f"({m['mttr']['n']} cerrados) · dentro del objetivo: {m['res_sla_pct'] if m['res_sla_pct'] is not None else '—'} %")
    print(f"  Abiertos: {m['open']} · vencidos: {m['overdue_count']}\n")
    print(f"  {'Severidad':<22}{'Total':>6}{'Abiertos':>9}  {'MTTA':>10} {'obj.':>7}  {'MTTR':>10} {'obj.':>7}")
    for g in m["by_severity"]:
        print(f"  {g['label']:<22}{g['total']:>6}{g['open']:>9}  {g['mtta']['mean']:>10} {g['target_ack']:>7}  "
              f"{g['mttr']['mean']:>10} {g['target_res']:>7}")
    for o in m["overdue"][:5]:
        print(f"  [VENCIDO] #{o['id']} sev {o['severity']} {o['device']}: {o['detail']}")
    c = m["changes"]
    print(f"\nCambios: {c['total']} · terminados {c['finished']} · éxito "
          f"{c['success_pct'] if c['success_pct'] is not None else '—'} % · rollbacks {c['rollbacks']} · fallidos "
          f"{c['failed']} · aprobación media {c['approval_time']['mean']}")
    conn.close()


def cmd_notify_test():
    """Fase 11: envía un aviso de prueba por Telegram (o lo simula)."""
    from app.db import audit, now_iso
    from app.notify import clean, mode, queue_notification
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)
    m = mode()
    if m == "apagado":
        print("[!] Avisos apagados: configure TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env (o NOTIFY_SIMULATE=1)")
        return
    nid = queue_notification(conn, "prueba", None,
                             clean(f"🧪 NOC · Aviso de prueba desde la consola ({Config.DEFAULT_OPERATOR})"),
                             f"test|{now_iso()}", sync=True)
    row = conn.execute("SELECT status, error FROM notifications WHERE id = ?", (nid,)).fetchone()
    audit(conn, Config.DEFAULT_OPERATOR, "notify.test", "notifications", nid, f"modo={m} estado={row['status']}",
          "ok" if row["status"] in ("enviado", "simulado") else "alerta")
    print(f"[{'OK' if row['status'] in ('enviado', 'simulado') else '!'}] Aviso #{nid} · modo {m} · "
          f"{row['status']}" + (f" · {row['error']}" if row["error"] else ""))
    conn.close()


def cmd_telegram_chat_id():
    """Fase 11: muestra los chats que le escribieron al bot (para TELEGRAM_CHAT_ID). No muestra el token."""
    from app.notify import get_chat_ids
    if not Config.TELEGRAM_BOT_TOKEN:
        print("[!] Primero ponga TELEGRAM_BOT_TOKEN en .env (lo entrega @BotFather)")
        return
    try:
        chats = get_chat_ids(Config.TELEGRAM_BOT_TOKEN)
    except RuntimeError as e:
        print(f"[!] {e}")
        return
    if not chats:
        print("[!] El bot no tiene mensajes: abra el bot en Telegram, envíele /start y repita este comando")
    for c in chats:
        print(f"  chat id: {c['id']:<16} tipo: {c['type']:<10} nombre: {c['name']}")
    if chats:
        print("\nCopie el chat id en .env como TELEGRAM_CHAT_ID=... y reinicie serve.py y el receptor")


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
    p_di = sub.add_parser("device-interfaces", help="Leer las interfaces reales del equipo")
    p_di.add_argument("equipo")
    p_di.add_argument("--eliminar-ausentes", action="store_true",
                      help="Eliminar del inventario las interfaces que el equipo ya no reporta")
    p_dg = sub.add_parser("device-diag", help="Ping o traceroute ejecutado por el equipo")
    p_dg.add_argument("equipo")
    p_dg.add_argument("tipo", choices=["ping", "traceroute"])
    p_dg.add_argument("destino", help="IPv4 de destino (redes permitidas: DIAG_ALLOWED_NETS)")
    sub.add_parser("check-consistency", help="Revisar reloj, consistencia y cadena de auditoría")
    p_dc = sub.add_parser("device-config", help="Guardar la configuración del equipo como versión (Fase 10.1)")
    p_dc.add_argument("equipo")
    p_dc.add_argument("--nota", default="", help="Motivo de la captura (opcional)")
    p_dv = sub.add_parser("device-configs", help="Versiones de configuración de un equipo")
    p_dv.add_argument("equipo")
    p_df = sub.add_parser("config-diff", help="Diferencias entre dos versiones (ID de device-configs)")
    p_df.add_argument("desde", type=int)
    p_df.add_argument("hasta", type=int)
    p_mt = sub.add_parser("metrics", help="Indicadores de operación: MTTA, MTTR, SLA y cambios (Fase 10.4)")
    p_mt.add_argument("--dias", type=int, default=30, choices=[7, 30, 90, 0], help="0 = todo el historial")
    p_mt.add_argument("--origen", default="todos", choices=["todos", "reales", "simulados"])
    sub.add_parser("notify-test", help="Enviar un aviso de prueba por Telegram (Fase 11)")
    sub.add_parser("telegram-chat-id", help="Ver el chat id de quien le escribió al bot (Fase 11)")
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
    elif args.command == "device-interfaces":
        cmd_device_interfaces(args.equipo, args.eliminar_ausentes)
    elif args.command == "device-diag":
        cmd_device_diag(args.equipo, args.tipo, args.destino)
    elif args.command == "check-consistency":
        cmd_check_consistency()
    elif args.command == "device-config":
        cmd_device_config(args.equipo, args.nota)
    elif args.command == "device-configs":
        cmd_device_configs(args.equipo)
    elif args.command == "config-diff":
        cmd_config_diff(args.desde, args.hasta)
    elif args.command == "metrics":
        cmd_metrics(args.dias, args.origen)
    elif args.command == "notify-test":
        cmd_notify_test()
    elif args.command == "telegram-chat-id":
        cmd_telegram_chat_id()
