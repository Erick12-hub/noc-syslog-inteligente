"""
Fase 12: REPORTE DE PRUEBAS para el informe (docs/pruebas/reporte_pruebas.md).

Ejecuta TODA la batería de pytest (bases temporales, sin red, sin el bot real)
y agrupa los resultados por categoría de calidad: funcionales, seguridad,
integridad, cambios y operación. Así el informe muestra QUÉ se probó, no solo
"N passed".

Uso:
    python scripts\\reporte_pruebas.py
"""
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import APP_VERSION  # noqa: E402

# archivo de pruebas -> (categoría, qué valida)
CATALOG = {
    "test_parser.py": ("Funcionales", "Lectura de Syslog RFC 3164/5424, Cisco, FortiGate y Huawei"),
    "test_ingest.py": ("Funcionales", "Ingesta, deduplicación e importación de archivos"),
    "test_api.py": ("Funcionales", "API de eventos, equipos e importación"),
    "test_incidents.py": ("Funcionales", "Incidentes, correlación y tablero"),
    "test_fechas.py": ("Funcionales", "Filtros de fecha en hora de Colombia"),
    "test_interfaz_puertos.py": ("Funcionales", "Interfaz y puertos en los eventos"),
    "test_interfaces_equipo.py": ("Funcionales", "Interfaces del inventario por equipo"),
    "test_tema.py": ("Funcionales", "Tema claro/oscuro de la interfaz"),
    "test_validacion.py": ("Seguridad", "Validación estricta de parámetros"),
    "test_auth.py": ("Seguridad", "Inicio de sesión, bloqueo, CSRF, roles y sesión"),
    "test_admin_seguridad.py": ("Seguridad", "Administración de usuarios y seguridad"),
    "test_seguridad.py": ("Seguridad", "Generador de configuraciones, consola segura e inyección a la IA"),
    "test_telegram_ia.py": ("Seguridad", "Avisos por Telegram y defensa del asistente de IA"),
    "test_auditoria_cadena.py": ("Integridad", "Auditoría encadenada con SHA-256"),
    "test_consistencia.py": ("Integridad", "Reloj NTP, consistencia y cadena automática"),
    "test_respaldos.py": ("Integridad", "Respaldo, verificación y restauración de la base"),
    "test_versiones_config.py": ("Cambios", "Versiones de configuración, ocultar secretos y diferencias"),
    "test_cambios.py": ("Cambios", "Solicitudes de cambio, matriz de riesgo y ventana"),
    "test_ejecucion_cambios.py": ("Cambios", "Aprobación, ejecución, verificación y rollback"),
    "test_conexiones.py": ("Operación", "Conexión con equipos (consola/SSH) y trazabilidad"),
    "test_configuracion_base.py": ("Operación", "Configuración base para el laboratorio"),
    "test_diagnostico.py": ("Operación", "Ping y traceroute desde el equipo"),
    "test_interfaces_reales.py": ("Operación", "Interfaces reales leídas del equipo"),
    "test_metricas.py": ("Operación", "MTTA, MTTR, SLA e indicadores de cambios"),
    "test_optimizacion.py": ("Rendimiento", "Índices, consultas y límites de la base"),
    "test_carga.py": ("Rendimiento", "Prueba de carga reducida y control de tormentas"),
}
ORDER = ["Funcionales", "Seguridad", "Integridad", "Cambios", "Operación", "Rendimiento", "Otras"]


def run_pytest(xml_path: Path) -> tuple[int, str]:
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml_path}"],
                       cwd=ROOT, capture_output=True, text=True)
    last = [line for line in p.stdout.strip().splitlines() if line.strip()]
    return p.returncode, (last[-1] if last else "")


def parse(xml_path: Path) -> dict:
    files = defaultdict(lambda: {"total": 0, "ok": 0, "fallas": 0, "omitidas": 0, "segundos": 0.0, "fallidas": []})
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        mod = (case.get("classname") or "").split(".")
        name = next((m for m in mod if m.startswith("test_")), "otros") + ".py"
        f = files[name]
        f["total"] += 1
        f["segundos"] += float(case.get("time") or 0)
        if case.find("failure") is not None or case.find("error") is not None:
            f["fallas"] += 1
            f["fallidas"].append(case.get("name"))
        elif case.find("skipped") is not None:
            f["omitidas"] += 1
        else:
            f["ok"] += 1
    return files


def render(files: dict, summary: str) -> str:
    total = sum(f["total"] for f in files.values())
    ok = sum(f["ok"] for f in files.values())
    fails = sum(f["fallas"] for f in files.values())
    secs = sum(f["segundos"] for f in files.values())
    by_cat = defaultdict(list)
    for name, f in files.items():
        cat, desc = CATALOG.get(name, ("Otras", "-"))
        by_cat[cat].append((name, desc, f))
    lines = ["# Reporte de pruebas - NOC Syslog Inteligente", "",
             "> Generado por `python scripts/reporte_pruebas.py`. Cada prueba usa una base de datos TEMPORAL, "
             "datos SIMULADOS y ninguna conexión real (equipos ni Telegram).", "",
             f"- Fecha: {datetime.now():%Y-%m-%d %H:%M}  ·  versión del NOC: {APP_VERSION}",
             f"- Equipo: {platform.system()} {platform.release()}  ·  Python {platform.python_version()}",
             f"- Resultado de pytest: `{summary}`", "",
             f"**{ok} de {total} pruebas superadas ({ok * 100 / total if total else 0:.1f} %), "
             f"{fails} fallidas, en {secs:.1f} s.**", "",
             "## Resumen por categoría", "",
             "| Categoría | Archivos | Pruebas | Superadas | Fallidas |", "|---|---:|---:|---:|---:|"]
    for cat in ORDER:
        if cat in by_cat:
            items = by_cat[cat]
            lines.append(f"| {cat} | {len(items)} | {sum(i[2]['total'] for i in items)} | "
                         f"{sum(i[2]['ok'] for i in items)} | {sum(i[2]['fallas'] for i in items)} |")
    lines += [f"| **Total** | **{len(files)}** | **{total}** | **{ok}** | **{fails}** |", ""]
    for cat in ORDER:
        if cat not in by_cat:
            continue
        lines += [f"## {cat}", "", "| Archivo | Qué valida | Pruebas | Resultado |", "|---|---|---:|---|"]
        for name, desc, f in sorted(by_cat[cat]):
            res = "Superadas" if f["fallas"] == 0 else f"{f['fallas']} fallidas: " + ", ".join(f["fallidas"][:5])
            lines.append(f"| `tests/{name}` | {desc} | {f['total']} | {res} |")
        lines.append("")
    return "\n".join(lines)


def main():
    with tempfile.TemporaryDirectory(prefix="noc_reporte_") as tmp:
        xml = Path(tmp) / "resultado.xml"
        print("[NOC] Ejecutando todas las pruebas (puede tardar ~1 minuto) ...")
        code, summary = run_pytest(xml)
        if not xml.exists():
            print("[!] pytest no generó resultados:", summary)
            return 2
        files = parse(xml)
    out = ROOT / "docs" / "pruebas" / "reporte_pruebas.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(files, summary), encoding="utf-8")
    print(f"   {summary}")
    print(f"[{'OK' if code == 0 else '!'}] Reporte: {out.relative_to(ROOT)}")
    return code


if __name__ == "__main__":
    sys.exit(main())
