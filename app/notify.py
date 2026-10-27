"""
Fase 11: ALERTAS POR TELEGRAM.

    GET  /api/notifications          Últimos avisos (auditor y administrador)
    GET  /api/notifications/status   Modo, destino (enmascarado) y severidad mínima
    POST /api/notifications/test     Envía un aviso de prueba (administrador)

QUÉ SE AVISA
    - Incidentes con severidad <= NOTIFY_MIN_SEVERITY (por defecto 0, 1 y 2):
      automáticos (eventos, reglas, tormentas, cadena de auditoría rota) o manuales.
    - Cambios que terminan ejecutados, revertidos o fallidos (Fase 10).

MODOS
    telegram   TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env -> se envía.
    simulado   Sin token y NOTIFY_SIMULATE=1 -> se registra como enviado sin red
               (sirve para demostrar el flujo sin crear un bot).
    apagado    Ninguno de los dos -> no se hace nada.

SEGURIDAD
    - El token es un secreto: solo vive en .env; nunca se audita, ni se muestra,
      ni aparece en los mensajes de error (solo el tipo de error).
    - El aviso lo arma el NOC con datos ESTRUCTURADOS (número, severidad, equipo,
      título del sistema). NUNCA incluye el texto del log: un mensaje fabricado
      no puede llegar al celular del operador ni a otro agente de IA que lea el
      chat (defensa contra prompt injection, Fase 11.2).
    - Texto plano (sin Markdown/HTML) para que nada se interprete como formato.
    - Anti-tormenta: el mismo incidente/correlación se agrupa durante
      NOTIFY_GROUP_MINUTES y hay un máximo de NOTIFY_MAX_PER_MINUTE avisos.
    - El envío va en un hilo aparte: si Telegram no responde, el receptor
      Syslog sigue recibiendo eventos.
    - Cada aviso queda en la tabla notifications (trazabilidad).
"""
import json
import queue
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, has_app_context, jsonify

from .auth import actor
from .config import Config
from .db import audit, connect, get_db, now_iso

bp = Blueprint("notify", __name__, url_prefix="/api/notifications")

API = "https://api.telegram.org"
TIMEOUT = 8
MAX_TEXT = 600
SEV_ICON = {0: "🔴", 1: "🔴", 2: "🟠", 3: "🟡"}
SEV_NAME = ["Emergency", "Alert", "Critical", "Error", "Warning", "Notice", "Informational", "Debug"]
CHANGE_ICON = {"ejecutado": "✅", "revertido": "↩️", "fallido": "❌"}
RE_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

_queue: "queue.Queue[tuple[str, int]]" = queue.Queue()
_worker = None
_worker_lock = threading.Lock()


def _cfg(name):
    """Configuración vigente: la de la app (pruebas) o la del .env (consola/receptor)."""
    if has_app_context() and name in current_app.config:
        return current_app.config[name]
    return getattr(Config, name, None)


def mode() -> str:
    if _cfg("TELEGRAM_BOT_TOKEN") and _cfg("TELEGRAM_CHAT_ID"):
        return "telegram"
    return "simulado" if _cfg("NOTIFY_SIMULATE") else "apagado"


def masked_chat() -> str:
    chat = str(_cfg("TELEGRAM_CHAT_ID") or "")
    return (chat[:2] + "•" * max(0, len(chat) - 4) + chat[-2:]) if len(chat) > 4 else ("•" * len(chat))


def clean(text: str) -> str:
    return RE_CONTROL.sub(" ", str(text or ""))[:MAX_TEXT]


# ---------------------------------------------------------------------------
# 1. Armar el aviso (solo datos estructurados)
# ---------------------------------------------------------------------------
def incident_text(conn, incident_id) -> tuple[str, int, str]:
    i = conn.execute("SELECT i.*, d.name AS device_name FROM incidents i LEFT JOIN devices d "
                     "ON d.id = i.device_id WHERE i.id = ?", (incident_id,)).fetchone()
    sim = " [SIM]" if i["is_simulated"] else ""
    lines = [f"{SEV_ICON.get(i['severity'], '⚪')} NOC · Incidente #{i['id']} · sev {i['severity']} "
             f"{SEV_NAME[i['severity']]}{sim}",
             f"Equipo: {i['device_name'] or '—'}",
             f"{i['title']}"]
    if i["event_id"]:
        ev = conn.execute("SELECT flags FROM syslog_events WHERE id = ?", (i["event_id"],)).fetchone()
        if ev and "posible_prompt_injection" in (ev["flags"] or ""):
            lines.append("⚠ El evento tiene posible inyección de instrucciones: revíselo en el NOC")
    lines.append(f"Abrir: {_cfg('NOC_URL')}/incidentes#{i['id']}")
    key = f"inc|{i['correlation_key'] or i['id']}"
    return clean("\n".join(lines)), i["severity"], key


def change_text(conn, change_id) -> str:
    c = conn.execute("SELECT * FROM change_requests WHERE id = ?", (change_id,)).fetchone()
    return clean("\n".join([
        f"{CHANGE_ICON.get(c['status'], '🛠')} NOC · Cambio #{c['id']} {c['status']} · riesgo {c['risk_level']}",
        f"Equipo: {c['device_name']}",
        f"{c['title']}",
        f"Resultado: {c['result'] or '—'}",
        f"Ejecutó: {c['executed_by'] or '—'}",
        f"Abrir: {_cfg('NOC_URL')}/cambios"]))


# ---------------------------------------------------------------------------
# 2. Registrar, agrupar y limitar
# ---------------------------------------------------------------------------
def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def queue_notification(conn, kind: str, ref_id, text: str, key: str, severity=None, sync=None) -> int | None:
    """Registra el aviso y lo envía (en segundo plano). Devuelve el id o None si está apagado."""
    m = mode()
    if m == "apagado":
        return None
    now = datetime.now(timezone.utc)
    status, error = "pendiente", None
    recent = conn.execute("SELECT id FROM notifications WHERE dedup_key = ? AND created_at >= ? "
                          "AND status IN ('pendiente', 'enviado', 'simulado') LIMIT 1",
                          (key, _iso(now - timedelta(minutes=_cfg("NOTIFY_GROUP_MINUTES"))))).fetchone()
    per_minute = conn.execute("SELECT COUNT(*) FROM notifications WHERE created_at >= ? "
                              "AND status IN ('pendiente', 'enviado', 'simulado')",
                              (_iso(now - timedelta(minutes=1)),)).fetchone()[0]
    if recent:
        status, error = "agrupado", f"ya se avisó en el aviso #{recent['id']}"
    elif per_minute >= _cfg("NOTIFY_MAX_PER_MINUTE"):
        status, error = "limitado", f"más de {_cfg('NOTIFY_MAX_PER_MINUTE')} avisos por minuto"
    elif m == "simulado":
        status = "simulado"
    cur = conn.execute("INSERT INTO notifications (channel, kind, ref_id, severity, text, status, error, "
                       "dedup_key, created_at, sent_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (m, kind, ref_id, severity, text, status, error, key, now_iso(),
                        now_iso() if status == "simulado" else None))
    conn.commit()
    nid = cur.lastrowid
    if status == "pendiente":
        db_path = str(_cfg("DATABASE_PATH"))
        if sync if sync is not None else _cfg("TESTING"):
            deliver(db_path, nid)
        else:
            _start_worker()
            _queue.put((db_path, nid))
    return nid


def notify_incident(conn, incident_id):
    """Llamado por create_incident(): avisa si la severidad lo amerita."""
    try:
        text, sev, key = incident_text(conn, incident_id)
        if sev <= _cfg("NOTIFY_MIN_SEVERITY"):
            queue_notification(conn, "incidente", incident_id, text, key, sev)
    except Exception as e:          # noqa: BLE001 - un aviso nunca debe romper la creación del incidente
        print(f"[AVISO] no se pudo registrar el aviso del incidente {incident_id}: {type(e).__name__}")


def notify_change(conn, change_id):
    try:
        queue_notification(conn, "cambio", change_id, change_text(conn, change_id), f"chg|{change_id}|{now_iso()}")
    except Exception as e:          # noqa: BLE001
        print(f"[AVISO] no se pudo registrar el aviso del cambio {change_id}: {type(e).__name__}")


# ---------------------------------------------------------------------------
# 3. Enviar
# ---------------------------------------------------------------------------
def http_send(token: str, chat_id: str, text: str) -> None:
    """POST sendMessage. Lanza RuntimeError con un mensaje SIN el token."""
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text,
                                   "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(f"{API}/bot{token}/sendMessage", data, timeout=TIMEOUT) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8", "replace")).get("description", "")
        except Exception:      # noqa: BLE001
            pass
        raise RuntimeError(f"Telegram respondió {e.code}: {detail[:120]}".replace(token, "<token>")) from None
    except Exception as e:      # noqa: BLE001 - sin red, DNS, tiempo agotado...
        raise RuntimeError(f"No se pudo contactar a Telegram ({type(e).__name__})") from None
    if not body.get("ok"):
        raise RuntimeError(f"Telegram rechazó el mensaje: {str(body.get('description', ''))[:120]}")


def deliver(db_path: str, nid: int) -> None:
    conn = connect(db_path)
    try:
        n = conn.execute("SELECT * FROM notifications WHERE id = ?", (nid,)).fetchone()
        try:
            http_send(_cfg("TELEGRAM_BOT_TOKEN"), _cfg("TELEGRAM_CHAT_ID"), n["text"])
            conn.execute("UPDATE notifications SET status = 'enviado', sent_at = ? WHERE id = ?", (now_iso(), nid))
            conn.commit()
        except RuntimeError as e:
            conn.execute("UPDATE notifications SET status = 'fallido', error = ? WHERE id = ?", (str(e)[:200], nid))
            conn.commit()
            audit(conn, "sistema", "notify.fallido", "notifications", nid, str(e)[:200], "alerta")
    finally:
        conn.close()


def _start_worker():
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, name="avisos-telegram", daemon=True)
            _worker.start()


def _loop():
    while True:
        db_path, nid = _queue.get()
        try:
            deliver(db_path, nid)
        except Exception as e:      # noqa: BLE001 - el hilo nunca muere
            print(f"[AVISO] error enviando el aviso {nid}: {type(e).__name__}")


def get_chat_ids(token: str) -> list[dict]:
    """Para configurar: lee getUpdates y devuelve los chats que le escribieron al bot."""
    try:
        with urllib.request.urlopen(f"{API}/bot{token}/getUpdates", timeout=TIMEOUT) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:      # noqa: BLE001
        raise RuntimeError(f"No se pudo consultar a Telegram ({type(e).__name__}): revise el token") from None
    chats = {}
    for u in body.get("result", []):
        chat = (u.get("message") or u.get("channel_post") or {}).get("chat") or {}
        if "id" in chat:
            chats[chat["id"]] = {"id": chat["id"], "type": chat.get("type"),
                                 "name": chat.get("title") or chat.get("first_name") or chat.get("username")}
    return list(chats.values())


# ---------------------------------------------------------------------------
# 4. API
# ---------------------------------------------------------------------------
@bp.get("/status")
def status():
    return jsonify(mode=mode(), chat=masked_chat(), min_severity=_cfg("NOTIFY_MIN_SEVERITY"),
                   min_severity_name=SEV_NAME[_cfg("NOTIFY_MIN_SEVERITY")],
                   group_minutes=_cfg("NOTIFY_GROUP_MINUTES"), max_per_minute=_cfg("NOTIFY_MAX_PER_MINUTE"))


@bp.get("")
def list_notifications():
    rows = get_db().execute("SELECT * FROM notifications ORDER BY id DESC LIMIT 30").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/test")
def test_notification():
    conn = get_db()
    if mode() == "apagado":
        return jsonify(errors=["Los avisos están apagados: configure TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID "
                               "en .env (o NOTIFY_SIMULATE=1) y reinicie el servidor"]), 409
    user = actor()
    text = clean(f"🧪 NOC · Aviso de prueba\nEnviado por {user} desde el NOC Syslog Inteligente\n"
                 f"Abrir: {_cfg('NOC_URL')}")
    nid = queue_notification(conn, "prueba", None, text, f"test|{now_iso()}", None, sync=True)
    row = conn.execute("SELECT * FROM notifications WHERE id = ?", (nid,)).fetchone()
    audit(conn, user, "notify.test", "notifications", nid, f"modo={mode()} estado={row['status']}",
          "ok" if row["status"] in ("enviado", "simulado") else "alerta")
    return jsonify(dict(row)), 200 if row["status"] in ("enviado", "simulado") else 502
