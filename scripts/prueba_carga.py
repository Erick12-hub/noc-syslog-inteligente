"""
Fase 12: PRUEBA DE CARGA del NOC - TODOS LOS DATOS SON SIMULADOS.

Usa una base de datos TEMPORAL (nunca toca data/noc.db) y nunca envía avisos
por Telegram (el token se anula dentro de la prueba). Mide:

  1. Ingesta: N mensajes Syslog SIM (Cisco, FortiGate, Huawei, varias
     severidades) por el mismo camino que el receptor: clasificación,
     reglas, incidentes y auditoría. Mensajes por segundo y latencia p50/p95/p99.
  2. Concurrencia: varios hilos escribiendo a la vez (como el receptor y la
     web): no debe haber errores "database is locked" y la cadena de
     auditoría debe quedar íntegra.
  3. Control de tormentas: un equipo envía más de STORM_MAX_PER_MINUTE
     mensajes en un minuto: se aceptan exactamente el límite y se descarta el resto.
  4. Consultas de la web con la base cargada (eventos, incidentes, tablero,
     indicadores): tiempo de respuesta p50/p95.

Uso:
    python scripts\\prueba_carga.py                      (2000 mensajes)
    python scripts\\prueba_carga.py --mensajes 5000 --hilos 4
    python scripts\\prueba_carga.py --reporte            (además escribe docs/pruebas/prueba_carga.md)
"""
import argparse
import platform
import secrets
import statistics
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import APP_VERSION                       # noqa: E402
from app.config import Config                     # noqa: E402
from app.db import connect, init_db, verify_audit_chain  # noqa: E402
from app.ingest import ingest                     # noqa: E402
from app.security import STORM                    # noqa: E402
from app.seed import seed_devices                 # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Equipos SIMULADOS de app/seed.py (documentación: 192.0.2.0/24 y 198.51.100.0/24)
DEVICES = [("192.0.2.1", "cisco", "SIM-CORE-RTR01"), ("192.0.2.10", "cisco", "SIM-DIST-SW01"),
           ("198.51.100.1", "forti", "SIM-EDGE-FW01"), ("198.51.100.20", "huawei", "SIM-BR-RTR02")]
# Mezcla realista: la mayoría informativos, pocos críticos
SEVERITIES = [6] * 10 + [5] * 6 + [4] * 3 + [3] * 2 + [2]


def percentile(values, p):
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    f = int(k)
    return s[f] + (s[min(f + 1, len(s) - 1)] - s[f]) * (k - f)


def message(i: int) -> tuple[str, str]:
    ip, kind, host = DEVICES[i % len(DEVICES)]
    sev = SEVERITIES[i % len(SEVERITIES)]
    n = datetime.now()
    ts = f"{MONTHS[n.month - 1]} {n.day:>2} {n:%H:%M:%S}"
    port = f"GigabitEthernet0/{i % 4}"
    if kind == "cisco":
        text = (f"%LINK-3-UPDOWN: Interface {port}, changed state to down" if sev <= 3 else
                f"%SYS-{sev}-CONFIG_I: Configured from console by sim_user{i % 7} (prueba de carga #{i})")
        return ip, f"<{23 * 8 + sev}>{i}: *{ts}.000: {host} {text}"
    if kind == "forti":
        lvl = {2: "critical", 3: "error", 4: "warning", 5: "notice", 6: "information"}[sev]
        return ip, (f'<{16 * 8 + sev}>date={n:%Y-%m-%d} time={n:%H:%M:%S} devname="{host}" logid="00000{i % 9}" '
                    f'type="traffic" level="{lvl}" srcip=10.0.{i % 250}.{i % 200} msg="prueba de carga SIM #{i}"')
    return ip, (f"<{23 * 8 + sev}>{n:%b %d %Y %H:%M:%S} {host} %%01IFNET/{sev}/LINK_STATE(l): "
                f"The line protocol IP on the interface {port} has entered the DOWN state. (SIM #{i})")


def prepare_db(path: Path):
    conn = connect(path)
    init_db(conn)
    seed_devices(conn)
    return conn


def test_ingest(db: Path, n: int) -> dict:
    conn = connect(db)
    lat, incidents, errors = [], 0, 0
    t0 = time.perf_counter()
    for i in range(n):
        ip, raw = message(i)
        s = time.perf_counter()
        try:
            r = ingest(conn, raw, ip, "simulador", is_simulated=True)
            incidents += 1 if r.get("incident") else 0
        except Exception:                         # noqa: BLE001 - se cuentan, no se ocultan
            errors += 1
        lat.append((time.perf_counter() - s) * 1000)
    total = time.perf_counter() - t0
    conn.close()
    return {"mensajes": n, "segundos": total, "por_segundo": n / total if total else 0,
            "p50": percentile(lat, 50), "p95": percentile(lat, 95), "p99": percentile(lat, 99),
            "max": max(lat) if lat else 0, "incidentes": incidents, "errores": errors}


def test_concurrency(db: Path, threads: int, per_thread: int) -> dict:
    errors, lock = [], threading.Lock()

    def worker(k):
        conn = connect(db)
        try:
            for j in range(per_thread):
                ip, raw = message(100000 + k * per_thread + j)
                try:
                    ingest(conn, raw, ip, "simulador", is_simulated=True)
                except Exception as e:            # noqa: BLE001
                    with lock:
                        errors.append(type(e).__name__ + ": " + str(e)[:80])
        finally:
            conn.close()

    t0 = time.perf_counter()
    ts = [threading.Thread(target=worker, args=(k,)) for k in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    total = time.perf_counter() - t0
    conn = connect(db)
    chain = verify_audit_chain(conn)
    conn.close()
    n = threads * per_thread
    return {"hilos": threads, "mensajes": n, "segundos": total, "por_segundo": n / total if total else 0,
            "errores": len(errors), "detalle_errores": errors[:3], "cadena_ok": chain["ok"],
            "auditoria_total": chain["total"]}


def test_storm(db: Path, extra: int = 50) -> dict:
    STORM.reset()
    limit = Config.STORM_MAX_PER_MINUTE
    conn = connect(db)
    accepted = dropped = 0
    for i in range(limit + extra):
        ip, raw = message(i * len(DEVICES))       # siempre el mismo equipo (192.0.2.1)
        r = ingest(conn, raw, ip, "udp")
        dropped += 1 if r.get("dropped") else 0
        accepted += 0 if r.get("dropped") else 1
    alerts = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action LIKE '%storm%' OR action LIKE '%tormenta%'"
                          ).fetchone()[0]
    conn.close()
    STORM.reset()
    return {"limite": limit, "enviados": limit + extra, "aceptados": accepted, "descartados": dropped,
            "alertas_auditoria": alerts, "ok": accepted == limit and dropped == extra}


def test_web(db: Path, repeat: int) -> dict:
    from app import create_app
    from app.auth import create_user

    class LoadConfig(Config):
        TESTING = True
        DATABASE_PATH = db

    app = create_app(LoadConfig)
    password = secrets.token_urlsafe(16)          # solo existe en esta base temporal; no se muestra
    conn = connect(db)
    create_user(conn, "carga_admin", password, "admin_seguridad", "Usuario temporal de la prueba de carga")
    conn.close()
    c = app.test_client()
    c.get("/login")
    with c.session_transaction() as s:
        token = s.get("csrf", "")
    c.post("/login", data={"username": "carga_admin", "password": password, "csrf_token": token})
    out = {}
    for name, url in [("Eventos (página 1)", "/api/events?limit=50"), ("Incidentes", "/api/incidents"),
                      ("Tablero", "/api/dashboard"), ("Indicadores 30 días", "/api/metrics?dias=30")]:
        lat, codes = [], set()
        for _ in range(repeat):
            s = time.perf_counter()
            r = c.get(url)
            lat.append((time.perf_counter() - s) * 1000)
            codes.add(r.status_code)
        out[name] = {"url": url, "p50": percentile(lat, 50), "p95": percentile(lat, 95), "codigos": sorted(codes)}
    return out


def render_markdown(r: dict) -> str:
    i, c, s, w = r["ingesta"], r["concurrencia"], r["tormenta"], r["web"]
    lines = [
        "# Prueba de carga - NOC Syslog Inteligente", "",
        "> Generado por `python scripts/prueba_carga.py --reporte`. **Todos los datos son SIMULADOS (SIM)**; "
        "se usó una base temporal y ningún aviso salió por Telegram.", "",
        f"- Fecha: {r['fecha']}  ·  versión del NOC: {APP_VERSION}",
        f"- Equipo de pruebas: {r['equipo']}  ·  Python {platform.python_version()}", "",
        "## 1. Ingesta (mismo camino que el receptor)", "",
        "| Mensajes | Tiempo | Mensajes/s | p50 | p95 | p99 | Máx. | Incidentes | Errores |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {i['mensajes']} | {i['segundos']:.2f} s | {i['por_segundo']:.0f} | {i['p50']:.2f} ms | "
        f"{i['p95']:.2f} ms | {i['p99']:.2f} ms | {i['max']:.2f} ms | {i['incidentes']} | {i['errores']} |", "",
        "## 2. Concurrencia (varios procesos escribiendo a la vez)", "",
        "| Hilos | Mensajes | Mensajes/s | Errores (bloqueos) | Cadena de auditoría |",
        "|---:|---:|---:|---:|---|",
        f"| {c['hilos']} | {c['mensajes']} | {c['por_segundo']:.0f} | {c['errores']} | "
        f"{'ÍNTEGRA' if c['cadena_ok'] else 'ROTA'} ({c['auditoria_total']} registros) |", "",
        "## 3. Control de tormentas", "",
        "| Límite por minuto | Enviados | Aceptados | Descartados | Resultado |", "|---:|---:|---:|---:|---|",
        f"| {s['limite']} | {s['enviados']} | {s['aceptados']} | {s['descartados']} | "
        f"{'Correcto' if s['ok'] else 'NO coincide'} |", "",
        "## 4. Consultas de la web con la base cargada", "",
        "| Consulta | p50 | p95 | Respuesta HTTP |", "|---|---:|---:|---|",
    ]
    for name, v in w.items():
        lines.append(f"| {name} (`{v['url']}`) | {v['p50']:.1f} ms | {v['p95']:.1f} ms | "
                     f"{', '.join(map(str, v['codigos']))} |")
    lines += ["", "## Conclusión", "", r["conclusion"], "",
              "Límites de la prueba: se ejecuta en un solo PC (sin red real entre equipos) y con la base "
              "SQLite local; mide la capacidad del procesamiento, no la de una red de producción.", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Prueba de carga del NOC (datos SIMULADOS, base temporal)")
    ap.add_argument("--mensajes", type=int, default=2000)
    ap.add_argument("--hilos", type=int, default=4)
    ap.add_argument("--por-hilo", type=int, default=250)
    ap.add_argument("--repeticiones", type=int, default=20, help="Veces que se repite cada consulta web")
    ap.add_argument("--reporte", action="store_true", help="Escribir docs/pruebas/prueba_carga.md")
    args = ap.parse_args()

    # Seguridad de la prueba: nunca avisos reales por Telegram
    Config.TELEGRAM_BOT_TOKEN = ""
    Config.TELEGRAM_CHAT_ID = ""
    Config.NOTIFY_SIMULATE = False

    with tempfile.TemporaryDirectory(prefix="noc_carga_") as tmp:
        db = Path(tmp) / "carga.db"
        prepare_db(db).close()
        print(f"[NOC] Prueba de carga · base TEMPORAL · datos SIMULADOS · versión {APP_VERSION}")
        print(f"\n1) Ingesta de {args.mensajes} mensajes ...")
        ing = test_ingest(db, args.mensajes)
        print(f"   {ing['por_segundo']:.0f} mensajes/s · p50 {ing['p50']:.2f} ms · p95 {ing['p95']:.2f} ms · "
              f"p99 {ing['p99']:.2f} ms · {ing['incidentes']} incidentes · {ing['errores']} errores")
        print(f"\n2) Concurrencia: {args.hilos} hilos x {args.por_hilo} mensajes ...")
        con = test_concurrency(db, args.hilos, args.por_hilo)
        print(f"   {con['por_segundo']:.0f} mensajes/s · {con['errores']} errores · cadena de auditoría "
              f"{'ÍNTEGRA' if con['cadena_ok'] else 'ROTA'} ({con['auditoria_total']} registros)")
        for e in con["detalle_errores"]:
            print(f"   ! {e}")
        print(f"\n3) Control de tormentas (límite {Config.STORM_MAX_PER_MINUTE}/min) ...")
        st = test_storm(db)
        print(f"   enviados {st['enviados']} · aceptados {st['aceptados']} · descartados {st['descartados']} · "
              f"{'CORRECTO' if st['ok'] else 'NO COINCIDE'}")
        print(f"\n4) Consultas web con {args.mensajes + con['mensajes'] + st['aceptados']} eventos cargados ...")
        web = test_web(db, args.repeticiones)
        for name, v in web.items():
            print(f"   {name:<22} p50 {v['p50']:7.1f} ms · p95 {v['p95']:7.1f} ms · HTTP {v['codigos']}")

    ok = (ing["errores"] == 0 and con["errores"] == 0 and con["cadena_ok"] and st["ok"]
          and all(v["codigos"] == [200] for v in web.values()))
    conclusion = (
        f"{'Prueba SUPERADA' if ok else 'Prueba con OBSERVACIONES'}: el NOC procesó "
        f"{ing['por_segundo']:.0f} mensajes/s en un solo proceso (p95 {ing['p95']:.1f} ms por mensaje), "
        f"{con['hilos']} escritores simultáneos sin bloqueos "
        f"{'y con la auditoría íntegra' if con['cadena_ok'] else 'pero la auditoría quedó ROTA'}, "
        f"el control de tormentas aceptó {st['aceptados']} de {st['enviados']} (límite {st['limite']}) "
        f"y las consultas de la web respondieron con p95 ≤ {max(v['p95'] for v in web.values()):.0f} ms.")
    print(f"\n{conclusion}")
    if args.reporte:
        out = ROOT / "docs" / "pruebas" / "prueba_carga.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_markdown({
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), "equipo": f"{platform.system()} {platform.release()}",
            "ingesta": ing, "concurrencia": con, "tormenta": st, "web": web, "conclusion": conclusion}),
            encoding="utf-8")
        print(f"\nReporte: {out.relative_to(ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
