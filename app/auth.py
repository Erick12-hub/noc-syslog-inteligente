"""
Autenticación, roles y protección CSRF (Fase 8, paso 8.1).

ROLES
    operador         Opera el NOC: inventario, eventos, incidentes, consola,
                     propuestas (crear, ejecutar, verificar). NO aprueba.
    auditor          SOLO LECTURA de todo, incluida la auditoría. No cambia
                     nada: quien revisa no debe poder modificar lo que revisa.
    admin_seguridad  Todo lo anterior + aprobar propuestas + usuarios y roles.
                     Nunca aprueba sus propias propuestas (separación de funciones).

CÓMO SE APLICAN LOS PERMISOS
    Una sola función, enforce(), revisa CADA petición antes de que llegue a la
    ruta (before_request). Así no depende de que cada ruta "se acuerde" de
    validar: si una ruta nueva no está en RULES, se aplica la regla por defecto
    (leer = todos los roles; cambiar = operador y admin_seguridad).

CONTRASEÑAS
    Se guarda solo el HASH (scrypt, de Werkzeug), nunca la contraseña. Un hash
    no se puede "deshacer": para verificar se calcula de nuevo y se compara.

CSRF (Cross-Site Request Forgery)
    Una página maliciosa abierta en otra pestaña podría intentar enviar un POST
    al NOC usando la sesión del operador. Para evitarlo, cada sesión tiene un
    token secreto que solo conocen las páginas del NOC; toda petición que cambia
    datos debe traerlo (encabezado X-CSRF-Token o campo csrf_token).
"""
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from flask import (Blueprint, current_app, g, has_request_context, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import audit, get_db, now_iso

bp = Blueprint("auth", __name__)

ROLES = ("operador", "auditor", "admin_seguridad")
ROLE_NAMES = {"operador": "Operador", "auditor": "Auditor", "admin_seguridad": "Administrador de seguridad"}

ALL = frozenset(ROLES)
OPS = frozenset({"operador", "admin_seguridad"})        # pueden operar (cambiar datos)
AUDIT = frozenset({"auditor", "admin_seguridad"})       # pueden ver la auditoría
ADMIN = frozenset({"admin_seguridad"})

# Rutas que NO exigen sesión
PUBLIC = {"auth.login_page", "auth.login", "static", "health"}

# Excepciones a la regla por defecto (endpoint -> roles permitidos)
RULES = {
    # Cerrar sesión es un POST (lleva token CSRF), pero NO cambia datos del NOC:
    # cualquier rol debe poder salir. Sin esta línea el auditor (solo lectura)
    # quedaba atrapado en su sesión (hallazgo de la prueba en vivo, Fase 8.1).
    "auth.logout": ALL,
    "audit.list_audit": AUDIT,          # la auditoría solo la ven auditor y admin
    "views.auditoria": AUDIT,
    "proposals.review": ADMIN,          # aprobar o rechazar propuestas
    "configgen.generate": OPS,          # es GET, pero queda auditado como acción
    "console.allowed": OPS,
    "views.consola": OPS,
    "views.configuraciones": OPS,
}

# Método de hash de contraseñas. scrypt es LENTO a propósito (~0,2 s): para el
# usuario no se nota, pero hace muy costoso probar millones de contraseñas si
# alguien roba la base. Las pruebas automáticas lo cambian por uno rápido.
HASH_METHOD = "scrypt"

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
RE_USERNAME = re.compile(r"^[a-z][a-z0-9._-]{2,29}$")
# Hash ficticio: si el usuario no existe se compara igual contra algo, para que
# la respuesta tarde lo mismo y no revele qué usuarios existen.
_DUMMY_HASH = generate_password_hash("contraseña-ficticia-para-igualar-tiempos")


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------
def validate_password(password: str, username: str) -> list[str]:
    """Política mínima de contraseñas. Devuelve la lista de problemas."""
    from .config import Config
    errors = []
    min_len = Config.PASSWORD_MIN_LENGTH
    if len(password) < min_len:
        errors.append(f"La contraseña debe tener al menos {min_len} caracteres")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        errors.append("La contraseña debe combinar letras y números")
    if username and username.lower() in password.lower():
        errors.append("La contraseña no puede contener el nombre de usuario")
    return errors


def create_user(conn, username: str, password: str, role: str, full_name: str = "",
                actor: str = "sistema") -> int:
    """Crea un usuario. Lanza ValueError con todos los problemas si algo no es válido."""
    username = (username or "").strip().lower()
    errors = []
    if not RE_USERNAME.match(username):
        errors.append("Usuario inválido: 3 a 30 caracteres, empieza con letra; letras minúsculas, números, . _ -")
    if role not in ROLES:
        errors.append(f"Rol inválido. Opciones: {', '.join(ROLES)}")
    errors += validate_password(password or "", username)
    if not errors and conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        errors.append(f"El usuario '{username}' ya existe")
    if errors:
        raise ValueError(errors)
    ts = now_iso()
    cur = conn.execute(
        "INSERT INTO users (username, full_name, password_hash, role, active, failed_attempts, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, 1, 0, ?, ?)",
        (username, (full_name or "").strip()[:80], generate_password_hash(password, method=HASH_METHOD),
         role, ts, ts))
    conn.commit()
    audit(conn, actor, "user.create", "users", cur.lastrowid, f"usuario={username} rol={role}")
    return cur.lastrowid


def _load_user(user_id):
    return get_db().execute(
        "SELECT id, username, full_name, role, active, locked_until FROM users WHERE id = ?",
        (user_id,)).fetchone()


def current_user():
    """Usuario de la sesión actual (o None). Se carga una vez por petición en g.user."""
    return g.get("user") if has_request_context() else None


def actor() -> str:
    """
    Nombre que se registra en la auditoría como responsable de la acción.
    Con sesión: el usuario real. Sin petición web (consola de comandos,
    receptor UDP): el operador por defecto del .env.
    """
    user = current_user()
    if user is not None:
        return user["username"]
    if has_request_context():
        return current_app.config["DEFAULT_OPERATOR"]
    from .config import Config
    return Config.DEFAULT_OPERATOR


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
def csrf_token() -> str:
    """Token de la sesión (se crea la primera vez). Se inserta en las plantillas."""
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def _csrf_ok() -> bool:
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    expected = session.get("csrf") or ""
    # compare_digest compara en tiempo constante (no revela cuántos caracteres coinciden)
    return bool(expected) and hmac.compare_digest(sent, expected)


# ---------------------------------------------------------------------------
# Control central de cada petición
# ---------------------------------------------------------------------------
def _is_api() -> bool:
    return request.path.startswith("/api/")


def _deny(status: int, message: str):
    if _is_api():
        return jsonify(errors=[message]), status
    return render_template("error.html", code=status, message=message), status


def allowed_roles(endpoint: str, method: str) -> frozenset:
    """Roles que pueden usar un endpoint con un método HTTP (regla por defecto + excepciones)."""
    if endpoint in RULES:
        return RULES[endpoint]
    return ALL if method in SAFE_METHODS else OPS


def enforce():
    """before_request: sesión, cuenta activa, CSRF y rol. Si algo falla, la ruta no se ejecuta."""
    g.user = None
    endpoint = request.endpoint or ""
    if endpoint in PUBLIC:
        if request.method not in SAFE_METHODS and not _csrf_ok():
            msg = "La sesión del formulario expiró. Recargue la página e intente de nuevo."
            if endpoint == "auth.login":
                csrf_token()
                return render_template("login.html", error=msg), 400
            return _deny(400, msg)
        return None

    user = _load_user(session["user_id"]) if "user_id" in session else None
    if user is None or not user["active"]:
        session.clear()
        if _is_api():
            return jsonify(errors=["Debe iniciar sesión"]), 401
        return redirect(url_for("auth.login_page", next=request.full_path.rstrip("?")))
    g.user = user

    if request.method not in SAFE_METHODS and not _csrf_ok():
        audit(get_db(), user["username"], "security.csrf", None, None,
              f"{request.method} {request.path}", "bloqueado")
        return _deny(403, "Token de seguridad (CSRF) inválido o ausente. Recargue la página.")

    if user["role"] not in allowed_roles(endpoint, request.method):
        audit(get_db(), user["username"], "security.forbidden", None, None,
              f"rol={user['role']} {request.method} {request.path}", "bloqueado")
        return _deny(403, f"Su rol ({ROLE_NAMES[user['role']]}) no permite esta acción.")
    return None


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
def _safe_next(target: str | None) -> str:
    """Solo se redirige a rutas internas ("/eventos"), nunca a otro sitio ("//malo.com")."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("views.dashboard")


@bp.get("/login")
def login_page():
    if "user_id" in session:
        return redirect(url_for("views.dashboard"))
    csrf_token()
    return render_template("login.html", next=request.args.get("next", ""))


@bp.post("/login")
def login():
    cfg = current_app.config
    conn = get_db()
    username = (request.form.get("username") or "").strip().lower()[:30]
    password = request.form.get("password") or ""
    nxt = request.form.get("next", "")
    generic = "Usuario o contraseña incorrectos."     # mismo mensaje si el usuario no existe
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    now = datetime.now(timezone.utc)

    def fail(message, status=401):
        return render_template("login.html", error=message, username=username, next=nxt), status

    if row is None:
        check_password_hash(_DUMMY_HASH, password)      # iguala el tiempo de respuesta
        audit(conn, "desconocido", "auth.login_fallido", "users", None,
              f"usuario inexistente={username!r} ip={request.remote_addr}", "bloqueado")
        return fail(generic)

    if not row["active"]:
        audit(conn, row["username"], "auth.login_fallido", "users", row["id"], "cuenta desactivada", "bloqueado")
        return fail(generic)

    if row["locked_until"] and row["locked_until"] > now_iso():
        until = datetime.fromisoformat(row["locked_until"].replace("Z", "+00:00"))
        local = until.astimezone(timezone(timedelta(hours=cfg["LOCAL_UTC_OFFSET"])))
        audit(conn, row["username"], "auth.login_fallido", "users", row["id"], "cuenta bloqueada", "bloqueado")
        return fail(f"Cuenta bloqueada por intentos fallidos hasta las {local:%H:%M} (hora de Colombia).", 423)

    if not check_password_hash(row["password_hash"], password):
        attempts = row["failed_attempts"] + 1
        locked_until = None
        if attempts >= cfg["MAX_LOGIN_ATTEMPTS"]:
            locked_until = (now + timedelta(minutes=cfg["LOCKOUT_MINUTES"])).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("UPDATE users SET failed_attempts = ?, locked_until = ?, updated_at = ? WHERE id = ?",
                     (0 if locked_until else attempts, locked_until, now_iso(), row["id"]))
        conn.commit()
        detail = f"intento {attempts} de {cfg['MAX_LOGIN_ATTEMPTS']} ip={request.remote_addr}"
        if locked_until:
            detail += f" -> BLOQUEADA {cfg['LOCKOUT_MINUTES']} min"
            audit(conn, row["username"], "auth.bloqueo", "users", row["id"], detail, "alerta")
            return fail(f"Demasiados intentos. Cuenta bloqueada {cfg['LOCKOUT_MINUTES']} minutos.", 423)
        audit(conn, row["username"], "auth.login_fallido", "users", row["id"], detail, "bloqueado")
        return fail(generic)

    # Inicio correcto: sesión NUEVA (evita la fijación de sesión) y contador en cero
    conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = ?, "
                 "updated_at = ? WHERE id = ?", (now_iso(), now_iso(), row["id"]))
    conn.commit()
    session.clear()
    session.permanent = True                       # dura SESSION_HOURS (un turno)
    session["user_id"] = row["id"]
    session["csrf"] = secrets.token_urlsafe(32)
    audit(conn, row["username"], "auth.login", "users", row["id"], f"rol={row['role']} ip={request.remote_addr}")
    return redirect(_safe_next(nxt))


@bp.post("/logout")
def logout():
    user = current_user()
    if user is not None:
        audit(get_db(), user["username"], "auth.logout", "users", user["id"], "")
    session.clear()
    return redirect(url_for("auth.login_page"))


@bp.get("/api/auth/me")
def me():
    u = current_user()
    return jsonify(username=u["username"], full_name=u["full_name"], role=u["role"],
                   role_name=ROLE_NAMES[u["role"]])


def init_app(app):
    """Registra el control central y las variables de plantilla."""
    app.permanent_session_lifetime = timedelta(hours=app.config["SESSION_HOURS"])
    app.before_request(enforce)

    @app.context_processor
    def inject_auth():
        user = current_user()
        return {"current_user": user, "csrf_token": csrf_token,
                "role_name": ROLE_NAMES.get(user["role"]) if user else None,
                "can": lambda endpoint, method="GET": bool(user) and
                user["role"] in allowed_roles(endpoint, method)}
