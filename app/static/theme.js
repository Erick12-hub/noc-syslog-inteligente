/*
 * Fase 7: selector de tema claro / oscuro.
 *
 * - Se carga en el <head> (antes de dibujar la página) para que no haya un
 *   "parpadeo" del tema equivocado al abrir cada página.
 * - Prioridad: 1) la elección guardada del operador, 2) el tema del sistema
 *   operativo (prefers-color-scheme), 3) oscuro.
 * - La elección se guarda en localStorage del navegador: es solo una
 *   preferencia visual de ESTE equipo, no un dato del NOC (no va a la base).
 *   localStorage puede fallar (navegación privada, bloqueos): por eso cada
 *   acceso va dentro de try/catch y, si falla, la página funciona igual.
 */
(function () {
  const KEY = "noc-tema";
  const root = document.documentElement;

  function saved() {
    try { return localStorage.getItem(KEY); } catch (_) { return null; }
  }
  function save(theme) {
    try { localStorage.setItem(KEY, theme); } catch (_) { /* sin almacenamiento: no se recuerda */ }
  }
  function systemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  function apply(theme) {
    root.dataset.theme = theme;               // <html data-theme="light|dark">
    const btn = document.getElementById("theme-toggle");
    if (btn) {
      const toLight = theme === "dark";
      // El botón muestra el tema AL QUE se va a cambiar
      btn.querySelector(".icon").textContent = toLight ? "☀" : "☾";
      btn.querySelector(".label").textContent = toLight ? "Claro" : "Oscuro";
      btn.setAttribute("aria-label", toLight ? "Cambiar a tema claro" : "Cambiar a tema oscuro");
      btn.title = btn.getAttribute("aria-label");
    }
  }

  // 1) Antes de dibujar: aplicar el tema guardado o el del sistema
  const initial = saved() || systemTheme();
  apply(initial);

  // 2) Cuando la página ya existe: conectar el botón
  document.addEventListener("DOMContentLoaded", () => {
    apply(root.dataset.theme);
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const next = root.dataset.theme === "dark" ? "light" : "dark";
      apply(next);
      save(next);
    });
  });

  // 3) Si el operador nunca eligió, seguir los cambios del sistema operativo
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: light)").addEventListener?.("change", (e) => {
      if (!saved()) apply(e.matches ? "light" : "dark");
    });
  }
})();
