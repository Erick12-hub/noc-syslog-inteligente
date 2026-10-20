"""
Ventana de administración de seguridad (Fase 8, paso 8.3).
SOLO para el rol admin_seguridad (regla "admin.*" en app/auth.py).

    GET  /api/admin/security                 Resumen: intentos fallidos, bloqueos,
                                             acciones bloqueadas, cadena, parámetros
    GET  /api/admin/users                    Usuarios (nunca se envía el hash)
    POST /api/admin/users                    Crear usuario
    POST /api/admin/users/<id>/role          Cambiar rol
    POST /api/admin/users/<id>/active        Activar / desactivar
    POST /api/admin/users/<id>/unlock        Desbloquear
    POST /api/admin/users/<id>/password      Restablecer contraseña
    POST /api/admin/users/<id>/name          Cambiar nombre visible

PROTECCIONES CONTRA ERRORES DEL PROPIO ADMINISTRADOR
  - No puede desactivarse ni cambiarse el rol a sí mismo (perdería el acceso
    en medio de su sesión).
  - El sistema nunca se queda sin un administrador de seguridad ACTIVO: si
    pasara, nadie podría aprobar propuestas ni gestionar usuarios desde la web.
Todas las acciones quedan en la auditoría encadenada.
"""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, request
from werkzeug.security import generate_password_hash

from . import auth
from .auth import ROLES, actor, create_user, current_user, validate_password
from .db import audit, get_db, now_iso, verify_audit_chain

bp = Blueprint("admin", __name__, url_prefix="/api/admin")

USER_FIELDS = ("id, username, full_name, role, active, failed_attempts, locked_until, "
               "last_login_at, created_at, updated_at")
# Acciones que cuentan como "bloqueadas por seguridad" en el resumen
BLOCKED_ACTIONS = ("security.forbidden", "security.csrf", "console.blocked",
                   "syslog.import_rechazado", "proposal.review")


def _since(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _user(conn, uid):
    return conn.execute(f"SELECT {USER_FIELDS} FROM users WHERE id = ?", (uid,)).fetchone()


def _public(row) -> dict:
    """Datos del usuario que se pueden mostrar (sin password_hash)."""
    d = dict(row)
    d["locked"] = bool(d["locked_until"] and d["locked_until"] > now_iso())
    return d


def _active_admins(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin_seguridad' AND active = 1").fetchone()[0]


def _load_target(conn, uid):
    """(usuario, error). Error si no existe."""
    row = _user(conn, uid)
    if row is None:
        return None, (jsonify(errors=["Usuario no encontrado"]), 404)
    return row, None


def _is_self(row) -> bool:
    return row["id"] == current_user()["id"]


# ---------------------------------------------------------------------------
# Resumen de seguridad
# ---------------------------------------------------------------------------
@bp.get("/security")
def security_summary():
    conn = get_db()
    cfg = current_app.config
    day = _since(24)
    q = lambda sql, *p: conn.execute(sql, p).fetchone()[0]          # noqa: E731

    chain = verify_audit_chain(conn)
    recent = conn.execute(
        "SELECT id, ts, actor, action, detail, result FROM audit_log "
        "WHERE (action LIKE 'auth.%' OR action LIKE 'security.%' OR action LIKE 'user.%' "
        "OR action = 'audit.verify' OR result IN ('bloqueado', 'alerta')) "
        "ORDER BY id DESC LIMIT 25").fetchall()
    return jsonify(
        failed_logins_24h=q("SELECT COUNT(*) FROM audit_log WHERE action = 'auth.login_fallido' AND ts >= ?", day),
        lockouts_24h=q("SELECT COUNT(*) FROM audit_log WHERE action = 'auth.bloqueo' AND ts >= ?", day),
        locked_accounts=q("SELECT COUNT(*) FROM users WHERE locked_until > ?", now_iso()),
        blocked_actions_24h=q(
            f"SELECT COUNT(*) FROM audit_log WHERE result = 'bloqueado' AND ts >= ? "
            f"AND action IN ({','.join('?' * len(BLOCKED_ACTIONS))})", day, *BLOCKED_ACTIONS),
        users_total=q("SELECT COUNT(*) FROM users"),
        users_active=q("SELECT COUNT(*) FROM users WHERE active = 1"),
        chain=chain,
        recent=[dict(r) for r in recent],
        # Parámetros vigentes: se LEEN del .env; cambiarlos exige editar el
        # archivo y reiniciar (a propósito: no se cambian desde la web).
        parameters=[
            ("Intentos fallidos antes de bloquear", cfg["MAX_LOGIN_ATTEMPTS"]),
            ("Minutos de bloqueo", cfg["LOCKOUT_MINUTES"]),
            ("Duración de la sesión (horas)", cfg["SESSION_HOURS"]),
            ("Longitud mínima de contraseña", cfg["PASSWORD_MIN_LENGTH"]),
            ("Hash de contraseñas", auth.HASH_METHOD),
            ("Cookie solo por HTTPS (Secure)", "sí" if cfg["SESSION_COOKIE_SECURE"] else "no (HTTP local)"),
            ("Horario laboral", cfg["BUSINESS_HOURS"]),
            ("Límite de tormentas (mensajes/min por fuente)", cfg["STORM_MAX_PER_MINUTE"]),
            ("Tolerancia de fecha futura (s)", cfg["FUTURE_TOLERANCE_SECONDS"]),
            ("Zona horaria (desfase UTC)", cfg["LOCAL_UTC_OFFSET"]),
        ],
    )


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------
@bp.get("/users")
def list_users():
    rows = get_db().execute(f"SELECT {USER_FIELDS} FROM users ORDER BY username").fetchall()
    return jsonify([_public(r) for r in rows])


@bp.post("/users")
def create():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        uid = create_user(conn, data.get("username", ""), data.get("password", ""),
                          data.get("role", ""), data.get("full_name", ""), actor=actor())
    except ValueError as e:
        return jsonify(errors=e.args[0]), 400
    return jsonify(_public(_user(conn, uid))), 201


@bp.post("/users/<int:uid>/role")
def change_role(uid):
    conn = get_db()
    row, err = _load_target(conn, uid)
    if err:
        return err
    role = (request.get_json(silent=True) or {}).get("role")
    if role not in ROLES:
        return jsonify(errors=[f"Rol inválido. Opciones: {', '.join(ROLES)}"]), 400
    if _is_self(row):
        return jsonify(errors=["No puede cambiar su propio rol"]), 409
    if row["role"] == "admin_seguridad" and role != "admin_seguridad" and row["active"] and _active_admins(conn) <= 1:
        return jsonify(errors=["Debe quedar al menos un administrador de seguridad activo"]), 409
    conn.execute("UPDATE users SET role = ?, updated_at = ? WHERE id = ?", (role, now_iso(), uid))
    conn.commit()
    audit(conn, actor(), "user.role", "users", uid, f"usuario={row['username']} {row['role']}->{role}")
    return jsonify(_public(_user(conn, uid)))


@bp.post("/users/<int:uid>/active")
def set_active(uid):
    conn = get_db()
    row, err = _load_target(conn, uid)
    if err:
        return err
    active = (request.get_json(silent=True) or {}).get("active")
    if not isinstance(active, bool):
        return jsonify(errors=["Indique active: true o false"]), 400
    if not active and _is_self(row):
        return jsonify(errors=["No puede desactivar su propia cuenta"]), 409
    if not active and row["role"] == "admin_seguridad" and row["active"] and _active_admins(conn) <= 1:
        return jsonify(errors=["Debe quedar al menos un administrador de seguridad activo"]), 409
    conn.execute("UPDATE users SET active = ?, updated_at = ? WHERE id = ?", (int(active), now_iso(), uid))
    conn.commit()
    # Un usuario desactivado pierde la sesión en su siguiente petición (ver auth.enforce)
    audit(conn, actor(), "user.activate" if active else "user.deactivate", "users", uid,
          f"usuario={row['username']}", "ok" if active else "alerta")
    return jsonify(_public(_user(conn, uid)))


@bp.post("/users/<int:uid>/unlock")
def unlock(uid):
    conn = get_db()
    row, err = _load_target(conn, uid)
    if err:
        return err
    conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL, updated_at = ? WHERE id = ?",
                 (now_iso(), uid))
    conn.commit()
    audit(conn, actor(), "user.unlock", "users", uid, f"usuario={row['username']}")
    return jsonify(_public(_user(conn, uid)))


@bp.post("/users/<int:uid>/password")
def reset_password(uid):
    conn = get_db()
    row, err = _load_target(conn, uid)
    if err:
        return err
    password = (request.get_json(silent=True) or {}).get("password") or ""
    problems = validate_password(password, row["username"])
    if problems:
        return jsonify(errors=problems), 400
    conn.execute("UPDATE users SET password_hash = ?, failed_attempts = 0, locked_until = NULL, "
                 "updated_at = ? WHERE id = ?",
                 (generate_password_hash(password, method=auth.HASH_METHOD), now_iso(), uid))
    conn.commit()
    # La contraseña NUNCA se escribe en la auditoría: solo que se cambió
    audit(conn, actor(), "user.password_reset", "users", uid, f"usuario={row['username']}")
    return jsonify(_public(_user(conn, uid)))


@bp.post("/users/<int:uid>/name")
def rename(uid):
    conn = get_db()
    row, err = _load_target(conn, uid)
    if err:
        return err
    name = ((request.get_json(silent=True) or {}).get("full_name") or "").strip()
    if not 2 <= len(name) <= 80:
        return jsonify(errors=["El nombre debe tener entre 2 y 80 caracteres"]), 400
    conn.execute("UPDATE users SET full_name = ?, updated_at = ? WHERE id = ?", (name, now_iso(), uid))
    conn.commit()
    audit(conn, actor(), "user.rename", "users", uid, f"usuario={row['username']} nombre={name}")
    return jsonify(_public(_user(conn, uid)))
