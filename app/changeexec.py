"""
Fase 10.3: APROBACIÓN, EJECUCIÓN, VERIFICACIÓN y ROLLBACK de los cambios.

    POST /api/changes/<id>/review      {decision: aprobar|rechazar, comment}   (admin_seguridad)
    POST /api/changes/<id>/execute     Ejecuta un cambio APROBADO dentro de su ventana
    POST /api/changes/<id>/rollback    {comment} Revierte un cambio ya ejecutado

APROBACIÓN (separación de funciones)
    - Revisa un administrador de seguridad que NO sea quien pidió el cambio.
    - Cada revisor decide una sola vez y con comentario (queda como evidencia).
    - Riesgo bajo/medio: 1 aprobación. Alto: 2 aprobaciones de personas distintas.
    - Un rechazo cierra el cambio.

EJECUCIÓN (todo queda en sesiones, comandos, versiones y auditoría)
    1. Controles: aprobado, dentro de la ventana, sin otro cambio en curso en el
       equipo y los comandos se validan OTRA VEZ (defensa en profundidad).
    2. Línea base: se lee la configuración (versión "antes").
    3. DERIVA: si la configuración ya no es la que se aprobó (alguien la cambió
       por fuera), NO se aplica nada: el cambio falla y se abre un incidente.
       No es deriva si la diferencia la dejó otro cambio aprobado que el NOC
       ejecutó después de enviar este (hallazgo de la prueba en vivo del 10.3).
    4. Se aplican los comandos (configure terminal ... end), verificando que
       responda el MISMO equipo físico (número de serie).
    5. Verificación: los comandos de verificación + la configuración "después"
       debe contener cada línea aplicada.
    6. Si algo falla -> ROLLBACK automático y nueva lectura. Si la configuración
       volvió a ser idéntica a la de antes: "revertido"; si no: "fallido" con
       incidente de severidad 2 (requiere intervención humana).
"""
import json
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from .auth import actor
from .changes import _lines, _public, check_commands, get_change
from .configversions import capture_config
from .db import audit, get_db, now_iso
from .incidents import create_incident

bp = Blueprint("changeexec", __name__, url_prefix="/api/changes")

MIN_COMMENT = 10


def _parse(iso):
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def approvals(conn, cid) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT reviewer, decision, comment, decided_at FROM change_approvals WHERE change_id = ? ORDER BY id",
        (cid,))]


# ---------------------------------------------------------------------------
# 1. Revisión
# ---------------------------------------------------------------------------
def review(conn, row, reviewer: str, decision: str, comment: str) -> tuple[dict, int]:
    if row["status"] != "pendiente":
        return {"errors": [f"Solo se revisa un cambio pendiente (estado actual: {row['status']})"]}, 409
    if decision not in ("aprobar", "rechazar"):
        return {"errors": ["Decisión inválida: aprobar o rechazar"]}, 400
    comment = (comment or "").strip()
    if not MIN_COMMENT <= len(comment) <= 500:
        return {"errors": [f"El comentario es obligatorio: entre {MIN_COMMENT} y 500 caracteres"]}, 400
    if reviewer == row["requested_by"]:
        audit(conn, reviewer, "change.review_bloqueado", "change_requests", row["id"],
              "intentó revisar su propio cambio", "bloqueado")
        return {"errors": ["Separación de funciones: nadie revisa su propio cambio"]}, 403
    if conn.execute("SELECT 1 FROM change_approvals WHERE change_id = ? AND reviewer = ?",
                    (row["id"], reviewer)).fetchone():
        return {"errors": ["Ya revisó este cambio: la segunda aprobación debe ser de OTRA persona"]}, 409
    ts = now_iso()
    word = "aprobado" if decision == "aprobar" else "rechazado"
    conn.execute("INSERT INTO change_approvals (change_id, reviewer, decision, comment, decided_at) "
                 "VALUES (?, ?, ?, ?, ?)", (row["id"], reviewer, word, comment, ts))
    approved = conn.execute("SELECT COUNT(*) FROM change_approvals WHERE change_id = ? AND decision = 'aprobado'",
                            (row["id"],)).fetchone()[0]
    if word == "rechazado":
        conn.execute("UPDATE change_requests SET status = 'rechazado', closed_at = ?, updated_at = ?, result = ? "
                     "WHERE id = ?", (ts, ts, f"Rechazado por {reviewer}: {comment}", row["id"]))
    elif approved >= row["approvals_required"]:
        conn.execute("UPDATE change_requests SET status = 'aprobado', approved_at = ?, updated_at = ? WHERE id = ?",
                     (ts, ts, row["id"]))
    else:
        conn.execute("UPDATE change_requests SET updated_at = ? WHERE id = ?", (ts, row["id"]))
    conn.commit()
    audit(conn, reviewer, f"change.{'approve' if word == 'aprobado' else 'reject'}", "change_requests", row["id"],
          f"'{row['title']}': {word} ({approved}/{row['approvals_required']}) · {comment[:120]}",
          "ok" if word == "aprobado" else "alerta")
    return {"approvals": approvals(conn, row["id"]), "approved": approved}, 200


# ---------------------------------------------------------------------------
# 2. Ejecución
# ---------------------------------------------------------------------------
def can_execute(conn, row, now: datetime) -> list[str]:
    errors = []
    if row["status"] != "aprobado":
        errors.append(f"Solo se ejecuta un cambio aprobado (estado actual: {row['status']})")
    if row["window_start"]:
        if now < _parse(row["window_start"]):
            errors.append("Todavía no empieza la ventana del cambio")
        elif now > _parse(row["window_end"]):
            errors.append("La ventana del cambio ya terminó: hay que reprogramarlo (nueva solicitud)")
    if row["device_id"] is None:
        errors.append("El equipo ya no existe en el inventario")
    busy = conn.execute("SELECT id FROM change_requests WHERE device_id = ? AND status = 'en_ejecucion' AND id != ?",
                        (row["device_id"], row["id"])).fetchone()
    if busy:
        errors.append(f"El cambio #{busy['id']} se está ejecutando en el mismo equipo")
    commands, rollback = _lines(row["commands"]), _lines(row["rollback"])
    errors += check_commands(commands, "Comandos") + check_commands(rollback, "Rollback")   # defensa en profundidad
    return errors


def expected_lines(commands: list[str]) -> list[str]:
    """Líneas que deben aparecer en la configuración después del cambio (las 'no ...' no se buscan)."""
    out = []
    for line in commands:
        cmd = " ".join(line.split())
        if cmd and not cmd.startswith("no ") and cmd != "exit":
            out.append(cmd)
    return out


def missing_lines(content: str, commands: list[str]) -> list[str]:
    present = {" ".join(l.split()) for l in content.splitlines()}
    return [c for c in expected_lines(commands) if c not in present]


def _finish(conn, cid, status, result, steps, post_version_id=None):
    ts = now_iso()
    conn.execute("UPDATE change_requests SET status = ?, result = ?, execution = ?, post_version_id = "
                 "COALESCE(?, post_version_id), closed_at = ?, updated_at = ? WHERE id = ?",
                 (status, result, json.dumps(steps, ensure_ascii=False), post_version_id, ts, ts, cid))
    conn.commit()


def execute_change(conn, row, user: str, now: datetime | None = None) -> tuple[dict, int]:
    from .connector import run_config, run_session
    now = now or datetime.now(timezone.utc)
    errors = can_execute(conn, row, now)
    if errors:
        return {"errors": errors}, 409
    device = conn.execute("SELECT * FROM devices WHERE id = ?", (row["device_id"],)).fetchone()
    cid, ts = row["id"], now_iso()
    commands, rollback, verify = _lines(row["commands"]), _lines(row["rollback"]), _lines(row["verify"])
    conn.execute("UPDATE change_requests SET status = 'en_ejecucion', executed_by = ?, executed_at = ?, "
                 "updated_at = ? WHERE id = ?", (user, ts, ts, cid))
    conn.commit()
    audit(conn, user, "change.execute", "change_requests", cid, f"{row['device_name']}: inicia '{row['title']}'")
    steps = []

    def step(name, ok, detail, **extra):
        steps.append({"step": name, "ok": ok, "detail": detail, "at": now_iso(), **extra})

    # --- 1. Línea base (antes) --------------------------------------------------
    pre, status = capture_config(conn, device, user, f"Antes del cambio #{cid}")
    if status not in (200, 201):
        step("Línea base", False, "; ".join(pre.get("errors", ["no se pudo leer la configuración"])))
        conn.execute("UPDATE change_requests SET status = 'aprobado', execution = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(steps, ensure_ascii=False), now_iso(), cid))
        conn.commit()
        audit(conn, user, "change.execute_abortado", "change_requests", cid,
              "no se pudo leer la configuración: no se aplicó nada (sigue aprobado)", "alerta")
        return {"errors": ["No se pudo leer la configuración antes del cambio: no se aplicó nada"] +
                          pre.get("errors", []), "steps": steps}, 502
    pre_v = pre["version"]
    conn.execute("UPDATE change_requests SET pre_version_id = ? WHERE id = ?", (pre_v["id"], cid))
    conn.commit()
    step("Línea base", True, f"v{pre_v['version_no']} · {pre_v['lines']} líneas · serie {pre_v['serial_number']}",
         version_id=pre_v["id"])

    # --- 2. Deriva: ¿es la configuración que se aprobó? ---------------------------------
    if row["baseline_version_id"]:
        base = conn.execute("SELECT version_no, sha256 FROM config_versions WHERE id = ?",
                            (row["baseline_version_id"],)).fetchone()
        # Lo que cambiaron OTROS cambios ejecutados por el NOC después de enviar este no es deriva
        by_noc = conn.execute(
            "SELECT c.id FROM change_requests c JOIN config_versions v ON v.id = c.post_version_id "
            "WHERE c.device_id = ? AND c.id != ? AND c.executed_at >= ? AND v.sha256 = ? ORDER BY c.id DESC LIMIT 1",
            (row["device_id"], cid, row["submitted_at"] or "", pre_v["sha256"])).fetchone()
        if base and base["sha256"] != pre_v["sha256"] and by_noc:
            step("Deriva", True, f"La configuración cambió solo por el cambio #{by_noc['id']}, ejecutado por el "
                                 f"NOC (v{base['version_no']} -> v{pre_v['version_no']})")
        elif base and base["sha256"] != pre_v["sha256"]:
            step("Deriva", False, f"La configuración cambió desde la aprobación (v{base['version_no']} -> "
                                  f"v{pre_v['version_no']}). No se aplicó nada")
            _finish(conn, cid, "fallido", "No aplicado: la configuración cambió por fuera después de aprobar "
                                          "(deriva). Revise el diff y cree una nueva solicitud", steps)
            inc = create_incident(conn, title=f"Deriva de configuración en {row['device_name']} (cambio #{cid})",
                                  severity=3, created_by="sistema", device_id=row["device_id"],
                                  correlation_key=f"cambio|{cid}",
                                  description="La configuración no es la que se aprobó: alguien la cambió por fuera "
                                              "del proceso de cambios.")
            audit(conn, user, "change.deriva", "change_requests", cid,
                  f"v{base['version_no']} != v{pre_v['version_no']} · incidente {inc}", "alerta")
            return _detail(conn, cid), 200
        else:
            step("Deriva", True, "La configuración es la misma que se aprobó")

    # --- 3. Aplicar ---------------------------------------------------------------
    applied, status = run_config(conn, device, commands, user, pre_v["serial_number"], f"cambio #{cid}")
    ok = status == 200
    step("Aplicar", ok, f"{len(commands)} líneas · sesión {applied.get('id', '-')}"
                        + ("" if ok else f" · {'; '.join(applied.get('errors', []))}"), session_id=applied.get("id"))
    if applied.get("wrong_device"):
        # No se aplicó nada y NO se hace rollback: sería sobre un equipo que no es el aprobado
        _finish(conn, cid, "fallido", "No aplicado: respondió otro equipo físico (cable o consola equivocados, "
                                      "o posible suplantación). No se hizo rollback", steps)
        inc = create_incident(conn, title=f"Cambio #{cid}: respondió otro equipo físico en {row['device_name']}",
                              severity=2, created_by="sistema", device_id=row["device_id"],
                              correlation_key=f"cambio|{cid}",
                              description="El número de serie no coincide con el de la línea base.")
        audit(conn, user, "change.equipo_distinto", "change_requests", cid, f"incidente {inc}", "alerta")
        return _detail(conn, cid), 200

    # --- 4. Verificar ------------------------------------------------------------
    post_v = None
    if ok and verify:
        vs, vstatus = run_session(conn, device, verify, user)
        bad = [c["command"] for c in vs.get("commands", []) if c["status"] != "ok" or "% Invalid" in (c["output"] or "")]
        ok = vstatus == 200 and not bad
        step("Verificación", ok, f"{len(verify)} comando(s) · sesión {vs.get('id', '-')}"
                                 + (f" · fallaron: {', '.join(bad)}" if bad else ""), session_id=vs.get("id"))
    if ok:
        post, pstatus = capture_config(conn, device, user, f"Después del cambio #{cid}")
        if pstatus in (200, 201):
            post_v = post["version"]
            missing = missing_lines(conn.execute("SELECT content FROM config_versions WHERE id = ?",
                                                 (post_v["id"],)).fetchone()[0], commands)
            ok = not missing
            step("Configuración después", ok, f"v{post_v['version_no']}" +
                 (" · sin diferencias con la de antes (ya estaba así)" if post_v["id"] == pre_v["id"] else "") +
                 (f" · NO aparecen: {', '.join(missing)}" if missing else " · todas las líneas aplicadas"),
                 version_id=post_v["id"])
        else:
            ok = False
            step("Configuración después", False, "; ".join(post.get("errors", ["no se pudo leer"])))

    if ok:
        _finish(conn, cid, "ejecutado", "Ejecutado y verificado", steps, post_v["id"])
        audit(conn, user, "change.executed", "change_requests", cid,
              f"{row['device_name']}: '{row['title']}' ejecutado y verificado (v{pre_v['version_no']} -> "
              f"v{post_v['version_no']})")
        return _detail(conn, cid), 200

    # --- 5. Rollback automático -------------------------------------------------------
    return _rollback(conn, row, device, user, pre_v, steps, rollback, automatic=True)


def _rollback(conn, row, device, user, pre_v, steps, rollback, automatic):
    from .connector import run_config
    cid = row["id"]
    rb, status = run_config(conn, device, rollback, user, pre_v["serial_number"], f"rollback #{cid}")
    steps.append({"step": "Rollback", "ok": status == 200, "at": now_iso(), "session_id": rb.get("id"),
                  "detail": f"{len(rollback)} líneas · sesión {rb.get('id', '-')}"
                            + ("" if status == 200 else f" · {'; '.join(rb.get('errors', []))}")})
    after, astatus = capture_config(conn, device, user, f"Después del rollback #{cid}")
    after_serial = None
    if astatus in (200, 201):
        s = conn.execute("SELECT serial_number FROM device_sessions WHERE id = ?", (after["session"],)).fetchone()
        after_serial = s["serial_number"] if s else None
    restored = (astatus in (200, 201) and after["version"]["sha256"] == pre_v["sha256"]
                and after_serial == pre_v["serial_number"])      # y leída del MISMO equipo físico
    after_id = after["version"]["id"] if astatus in (200, 201) else None
    steps.append({"step": "Comparar con la de antes", "ok": restored, "at": now_iso(), "version_id": after_id,
                  "detail": "Idéntica a la configuración de antes" if restored else
                            "NO quedó igual a la de antes: requiere revisión manual"})
    why = "automático por falla" if automatic else "manual"
    if restored:
        _finish(conn, cid, "revertido", f"Revertido ({why}): el equipo quedó como antes del cambio", steps, after_id)
        audit(conn, user, "change.rollback", "change_requests", cid,
              f"{row['device_name']}: rollback {why}, configuración restaurada", "alerta")
        return _detail(conn, cid), 200
    _finish(conn, cid, "fallido", f"Falló y el rollback ({why}) no restauró la configuración", steps, after_id)
    inc = create_incident(conn, title=f"Cambio #{cid} falló en {row['device_name']}: rollback incompleto",
                          severity=2, created_by="sistema", device_id=row["device_id"],
                          correlation_key=f"cambio|{cid}",
                          description="El rollback no dejó la configuración igual a la de antes. Revise el diff "
                                      "entre la versión anterior y la actual.")
    audit(conn, user, "change.rollback_fallido", "change_requests", cid,
          f"{row['device_name']}: configuración distinta a la de antes · incidente {inc}", "alerta")
    return _detail(conn, cid), 200


def manual_rollback(conn, row, user, comment) -> tuple[dict, int]:
    if row["status"] != "ejecutado":
        return {"errors": [f"Solo se revierte un cambio ejecutado (estado actual: {row['status']})"]}, 409
    comment = (comment or "").strip()
    if not MIN_COMMENT <= len(comment) <= 500:
        return {"errors": [f"Explique por qué se revierte: entre {MIN_COMMENT} y 500 caracteres"]}, 400
    device = conn.execute("SELECT * FROM devices WHERE id = ?", (row["device_id"],)).fetchone()
    if device is None:
        return {"errors": ["El equipo ya no existe en el inventario"]}, 409
    pre_v = conn.execute("SELECT * FROM config_versions WHERE id = ?", (row["pre_version_id"],)).fetchone()
    steps = json.loads(row["execution"] or "[]")
    steps.append({"step": "Rollback solicitado", "ok": True, "at": now_iso(), "detail": f"{user}: {comment}"})
    audit(conn, user, "change.rollback_manual", "change_requests", row["id"], comment[:200], "alerta")
    return _rollback(conn, row, device, user, dict(pre_v), steps, _lines(row["rollback"]), automatic=False)


# ---------------------------------------------------------------------------
# 3. Detalle y API
# ---------------------------------------------------------------------------
def _detail(conn, cid) -> dict:
    d = _public(get_change(conn, cid))
    d["approvals"] = approvals(conn, cid)
    d["execution"] = json.loads(d["execution"]) if d.get("execution") else []
    return d


def _load(cid):
    conn = get_db()
    row = get_change(conn, cid)
    return conn, row


@bp.post("/<int:cid>/review")
def review_change(cid):
    conn, row = _load(cid)
    if row is None:
        return jsonify(errors=["Cambio no encontrado"]), 404
    data = request.get_json(silent=True) or {}
    result, status = review(conn, row, actor(), str(data.get("decision") or ""), str(data.get("comment") or ""))
    if status != 200:
        return jsonify(result), status
    return jsonify(_detail(conn, cid))


@bp.post("/<int:cid>/execute")
def execute(cid):
    conn, row = _load(cid)
    if row is None:
        return jsonify(errors=["Cambio no encontrado"]), 404
    result, status = execute_change(conn, row, actor())
    return jsonify(result), status


@bp.post("/<int:cid>/rollback")
def rollback(cid):
    conn, row = _load(cid)
    if row is None:
        return jsonify(errors=["Cambio no encontrado"]), 404
    data = request.get_json(silent=True) or {}
    result, status = manual_rollback(conn, row, actor(), str(data.get("comment") or ""))
    return jsonify(result), status
