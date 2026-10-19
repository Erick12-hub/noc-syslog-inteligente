/*
 * Funciones comunes a todas las páginas.
 *
 * SEGURIDAD: todo texto que viene de la base de datos (y en especial de los
 * logs) se inserta con textContent, NUNCA con innerHTML. Así, si un log trae
 * "<script>...</script>", el navegador lo muestra como texto y no lo ejecuta
 * (prevención de XSS: Cross-Site Scripting).
 */

/* ---------------------------------------------------------------------------
 * Fase 8: seguridad de las peticiones.
 * Se envuelve fetch() UNA sola vez para todas las páginas:
 *  - Agrega el token anti-CSRF (de <meta name="csrf-token">) a toda petición
 *    que cambia datos (POST, PUT, DELETE...) hacia el propio NOC.
 *  - Si la sesión venció (401), lleva al inicio de sesión y vuelve luego aquí.
 * ------------------------------------------------------------------------- */
const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.content || "";
const _fetch = window.fetch.bind(window);
window.fetch = async (url, options = {}) => {
  const method = (options.method || "GET").toUpperCase();
  const sameOrigin = new URL(url, location.href).origin === location.origin;
  if (sameOrigin && !["GET", "HEAD", "OPTIONS"].includes(method)) {
    options.headers = new Headers(options.headers || {});
    options.headers.set("X-CSRF-Token", CSRF_TOKEN);
  }
  const res = await _fetch(url, options);
  if (res.status === 401 && sameOrigin) {
    location.href = "/login?next=" + encodeURIComponent(location.pathname);
  }
  return res;
};

const SEVERITY = ["Emergency", "Alert", "Critical", "Error", "Warning", "Notice", "Informational", "Debug"];

/** Crea un elemento HTML con texto seguro y clases opcionales. */
function el(tag, text = "", className = "") {
  const node = document.createElement(tag);
  if (text !== null && text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

/** Llamada a la API que devuelve JSON o lanza un error con los mensajes del servidor. */
async function api(url, options = {}) {
  const res = await fetch(url, options);
  let body = null;
  try { body = await res.json(); } catch (_) { /* respuesta sin JSON */ }
  if (!res.ok) {
    const msgs = (body && (body.errors || [body.error])) || [`Error HTTP ${res.status}`];
    throw new Error(msgs.filter(Boolean).join("\n"));
  }
  return body;
}

/** Fecha UTC (ISO) -> hora local de Colombia legible. */
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("es-CO", { dateStyle: "short", timeStyle: "medium" });
}

/** Etiqueta de severidad con color Y texto (no depende solo del color). */
function severityBadge(sev) {
  return el("span", `${sev} ${SEVERITY[sev] || ""}`, `sev sev-${sev}`);
}

/** Mensaje temporal en la esquina inferior. */
function toast(message, kind = "ok") {
  const t = document.getElementById("toast");
  t.textContent = message;
  t.className = `toast show ${kind}`;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => (t.className = "toast"), 4000);
}
