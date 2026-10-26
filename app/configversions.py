"""
Fase 10.1: VERSIONES DE CONFIGURACIÓN de cada equipo, con diferencias (diff).

    POST /api/devices/<id>/configs        Lee la configuración del equipo y la
                                          guarda como versión nueva (si cambió)
    GET  /api/devices/<id>/configs        Versiones del equipo (sin el texto)
    GET  /api/configs/<vid>               Una versión con su texto
    GET  /api/configs/diff?from=A&to=B    Diferencias entre dos versiones

POR QUÉ
    Para gestionar cambios (Fase 10.2-10.3) hay que saber CÓMO estaba el equipo
    antes y después. Cada versión guarda: quién la tomó, cuándo, de qué equipo
    FÍSICO (número de serie), la huella SHA-256 y el texto de la configuración.

SEGURIDAD
    - "show running-config" expone secretos (enable secret, usuarios, comunidad
      SNMP, llaves). Sigue BLOQUEADO en la sesión normal: solo se acepta por
      esta ruta, que OCULTA los secretos ANTES de guardar nada (ni en la versión
      ni en el historial de comandos). En la base nunca queda un secreto.
    - La configuración es un dato NO confiable: se guarda como texto y se
      muestra con textContent; nunca se ejecuta.
    - Las versiones son evidencia: un trigger impide modificarlas o borrarlas.
    - Si la configuración cambió desde la versión anterior, se audita como
      ALERTA: alguien la cambió (en la Fase 10.3 se cruzará con los cambios
      aprobados para separar lo autorizado de lo no autorizado).
"""
import difflib
import hashlib
import re

from flask import Blueprint, jsonify, request

from .auth import actor
from .db import audit, get_db, now_iso

bp = Blueprint("configversions", __name__, url_prefix="/api")

# Comando que lee la configuración en ejecución, por plataforma
CAPTURE_COMMAND = {"cisco_ios": "show running-config", "cisco_xe": "show running-config",
                   "huawei": "display current-configuration", "fortinet": "show full-configuration"}
MAX_CONFIG = 512 * 1024           # una configuración real de router/switch ocupa 5-60 KB
MAX_NOTE = 200
MASK = "<oculto>"
MAX_DIFF_LINES = 2000

# ---------------------------------------------------------------------------
# 1. Ocultar secretos
#    Palabra clave + (tipo opcional: 0, 5, 7, 9, ENC, cipher...) + valor  ->  valor oculto
#      enable secret 9 $9$abc...            -> enable secret 9 <oculto>
#      username x privilege 15 secret 9 $9$ -> username x privilege 15 secret 9 <oculto>
#      snmp-server community publica RO     -> snmp-server community <oculto> RO
#      set password ENC AbC...    (Fortinet)-> set password ENC <oculto>
#      local-user a password irreversible-cipher $1c$... (Huawei) -> ... <oculto>
# ---------------------------------------------------------------------------
RE_SECRET = re.compile(
    r"(?i)\b(secret|password|passwd|community|key-string|authentication-key|pre-shared-key|"
    r"psksecret|passphrase|key)"
    r"((?:\s+(?:\d{1,2}|ENC|cipher|simple|irreversible-cipher))?)"
    r"\s+(\S+)")
# Casos con el secreto en otra posición: "ntp authentication-key 1 md5 <clave> 7"
RE_SPECIAL = [re.compile(r"(?i)\b(authentication-key\s+\d+\s+md5)\s+(\S+)")]
RE_KEY_BLOCK_START = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
RE_KEY_BLOCK_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
# Palabras que NO esconden un secreto aunque contengan "key" o "password"
NOT_SECRET = re.compile(r"(?i)^\s*(service password-encryption|no service password-encryption|"
                        r"crypto key generate|key chain|password encryption aes|"
                        r"security passwords min-length)")


def mask_secrets(text: str) -> tuple[str, int]:
    """Devuelve (texto sin secretos, cuántas líneas se ocultaron)."""
    out, masked, in_key = [], 0, False
    for line in text.splitlines():
        if in_key or RE_KEY_BLOCK_START.search(line):
            in_key = not RE_KEY_BLOCK_END.search(line)
            if RE_KEY_BLOCK_START.search(line) or RE_KEY_BLOCK_END.search(line):
                out.append(line)
            else:
                out.append(MASK)
                masked += 1
            continue
        if MASK not in line and not NOT_SECRET.match(line):      # MASK: ya estaba oculto
            new = line
            for rx in RE_SPECIAL:
                new = rx.sub(lambda m: f"{m.group(1)} {MASK}", new)
            if new == line:
                new = RE_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)} {MASK}", line)
            if new != line:
                masked += 1
                line = new
        out.append(line)
    return "\n".join(out), masked


# ---------------------------------------------------------------------------
# 2. Normalizar: quitar lo que cambia SIN que cambie la configuración
#    (fechas de "último cambio", tamaño en bytes, reloj del NTP...). Si no se
#    quitara, cada lectura parecería una versión nueva.
# ---------------------------------------------------------------------------
VOLATILE = [re.compile(p) for p in (
    r"^Building configuration\.\.\.$",
    r"^Current configuration\s*:\s*\d+ bytes$",
    r"^! Last configuration change at ",
    r"^! NVRAM config last updated at ",
    r"^! No configuration change since last restart",
    r"^ntp clock-period \d+$",
    r"^!Software Version ",                    # Huawei
    r"^!Last configuration was (updated|saved) at ",
    r"^#config-version=",                       # Fortinet
    r"^#conf_file_ver=",
    r"^#buildno=",
    r"^#global_vdom=",
)]


def normalize(text: str) -> str:
    lines = [l.rstrip() for l in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [l for l in lines if not any(p.match(l) for p in VOLATILE)]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def prepare(raw: str) -> tuple[str, int]:
    """Lo que se guarda: configuración normalizada y SIN secretos."""
    clean, masked = mask_secrets(normalize(raw))
    return clean, masked


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 3. Diferencias
# ---------------------------------------------------------------------------
def diff_lines(a: str, b: str, name_a: str, name_b: str) -> dict:
    """Diff unificado (como 'git diff'): + agregada, - quitada, 3 líneas de contexto."""
    lines = list(difflib.unified_diff(a.splitlines(), b.splitlines(), name_a, name_b, lineterm="", n=3))
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    truncated = len(lines) > MAX_DIFF_LINES
    return {"lines": lines[:MAX_DIFF_LINES], "added": added, "removed": removed, "truncated": truncated}


def _label(v) -> str:
    return f"{v['device_name']} v{v['version_no']} ({v['captured_at']})"


# ---------------------------------------------------------------------------
# 4. Captura
# ---------------------------------------------------------------------------
def _public(row, with_content=False) -> dict:
    d = dict(row)
    if not with_content:
        d.pop("content", None)
    return d


def capture_config(conn, device, user: str, note: str = "") -> tuple[dict, int]:
    """Lee la configuración del equipo y guarda una versión nueva si cambió."""
    from .connector import run_session            # import tardío: evita importaciones circulares
    note = (note or "").strip()
    if len(note) > MAX_NOTE:
        return {"errors": [f"La nota admite máximo {MAX_NOTE} caracteres"]}, 400
    command = CAPTURE_COMMAND.get(device["platform"] or "")
    if command is None:
        return {"errors": ["Elija la plataforma del equipo en el inventario"]}, 400

    session, status = run_session(conn, device, [command], user, sanitize=lambda raw: prepare(raw)[0])
    if status != 200:
        return session, status
    cmd = next((c for c in session["commands"] if c["command"] == command), None)
    if cmd is None or cmd["status"] != "ok":
        return {"errors": ["El equipo no entregó la configuración"], "session": session["id"]}, 502
    content = cmd["output"]                         # ya normalizada y sin secretos (sanitize)
    if len(content.encode("utf-8")) > MAX_CONFIG:
        return {"errors": [f"La configuración supera {MAX_CONFIG // 1024} KB"], "session": session["id"]}, 413
    if not content.strip() or len(content.splitlines()) < 3:
        return {"errors": ["La salida no parece una configuración (muy corta o vacía)"],
                "session": session["id"]}, 502
    masked = len(re.findall(re.escape(MASK), content))
    digest = sha256(content)
    warnings = list(session["warnings"])

    prev = conn.execute("SELECT * FROM config_versions WHERE device_id = ? ORDER BY version_no DESC LIMIT 1",
                        (device["id"],)).fetchone()
    if prev is not None and prev["serial_number"] and session["serial_number"] \
            and prev["serial_number"] != session["serial_number"]:
        warnings.append(f"La versión anterior es de OTRO equipo físico ({prev['serial_number']}); "
                        f"ahora responde {session['serial_number']}. Compare con cuidado")
    if prev is not None and prev["sha256"] == digest:
        audit(conn, user, "config.capture", "config_versions", prev["id"],
              f"{device['name']}: sin cambios desde v{prev['version_no']} ({digest[:12]})")
        return {"changed": False, "version": _public(prev), "previous": None, "session": session["id"],
                "masked": masked, "warnings": warnings,
                "message": f"Sin cambios desde la versión {prev['version_no']}"}, 200

    added = removed = None
    if prev is not None:
        d = diff_lines(prev["content"], content, "", "")
        added, removed = d["added"], d["removed"]
    number = (prev["version_no"] + 1) if prev is not None else 1
    cur = conn.execute(
        "INSERT INTO config_versions (device_id, device_name, version_no, session_id, captured_by, captured_at, "
        "serial_number, command, sha256, lines, masked, added, removed, note, is_simulated, content) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (device["id"], device["name"], number, session["id"], user, now_iso(), session["serial_number"], command,
         digest, len(content.splitlines()), masked, added, removed, note or None,
         int(bool(session["is_simulated"])), content))
    conn.commit()
    vid = cur.lastrowid
    if prev is None:
        audit(conn, user, "config.capture", "config_versions", vid,
              f"{device['name']}: versión inicial v1 ({len(content.splitlines())} líneas, "
              f"{masked} secretos ocultos, {digest[:12]})")
    else:
        audit(conn, user, "config.changed", "config_versions", vid,
              f"{device['name']}: v{number} cambió respecto a v{prev['version_no']} (+{added} -{removed})",
              "alerta")
    row = conn.execute("SELECT * FROM config_versions WHERE id = ?", (vid,)).fetchone()
    return {"changed": True, "version": _public(row), "previous": _public(prev) if prev else None,
            "session": session["id"], "masked": masked, "warnings": warnings,
            "message": (f"Versión inicial guardada (v1)" if prev is None else
                        f"La configuración CAMBIÓ: v{number} (+{added} -{removed} respecto a v{prev['version_no']})")}, 201


def compare(conn, id_a: int, id_b: int) -> tuple[dict, int]:
    a = conn.execute("SELECT * FROM config_versions WHERE id = ?", (id_a,)).fetchone()
    b = conn.execute("SELECT * FROM config_versions WHERE id = ?", (id_b,)).fetchone()
    if a is None or b is None:
        return {"errors": ["Versión no encontrada"]}, 404
    warnings = []
    if a["device_id"] != b["device_id"]:
        warnings.append("Compara configuraciones de DOS equipos distintos")
    elif a["serial_number"] and b["serial_number"] and a["serial_number"] != b["serial_number"]:
        warnings.append(f"Las versiones son de equipos físicos distintos ({a['serial_number']} y "
                        f"{b['serial_number']})")
    d = diff_lines(a["content"], b["content"], _label(a), _label(b))
    return {"from": _public(a), "to": _public(b), "identical": a["sha256"] == b["sha256"],
            "warnings": warnings, **d}, 200


# ---------------------------------------------------------------------------
# 5. API
# ---------------------------------------------------------------------------
@bp.post("/devices/<int:device_id>/configs")
def capture(device_id):
    conn = get_db()
    device = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if device is None:
        return jsonify(errors=["Equipo no encontrado"]), 404
    data = request.get_json(silent=True) or {}
    result, status = capture_config(conn, device, actor(), str(data.get("note") or ""))
    return jsonify(result), status


@bp.get("/devices/<int:device_id>/configs")
def list_configs(device_id):
    rows = get_db().execute(
        "SELECT * FROM config_versions WHERE device_id = ? ORDER BY version_no DESC", (device_id,)).fetchall()
    return jsonify([_public(r) for r in rows])


@bp.get("/configs/<int:vid>")
def get_config(vid):
    row = get_db().execute("SELECT * FROM config_versions WHERE id = ?", (vid,)).fetchone()
    if row is None:
        return jsonify(errors=["Versión no encontrada"]), 404
    return jsonify(_public(row, with_content=True))


@bp.get("/configs/diff")
def diff():
    try:
        a, b = int(request.args.get("from", "")), int(request.args.get("to", ""))
    except ValueError:
        return jsonify(errors=["Indique dos versiones: ?from=ID&to=ID"]), 400
    result, status = compare(get_db(), a, b)
    return jsonify(result), status
