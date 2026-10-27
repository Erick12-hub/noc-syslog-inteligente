/*
 * Fase 8.3: ventana de administración de seguridad.
 * Consume /api/admin/security y /api/admin/users (solo admin_seguridad).
 * Todo texto de la base se inserta con textContent (el(...)), nunca innerHTML.
 */
const ROLE_LABEL = { operador: "Operador", auditor: "Auditor", admin_seguridad: "Administrador de seguridad" };
const RESULT_CLS = { ok: "ok", alerta: "warn", bloqueado: "bad", error: "bad" };
let me = null;

/** POST JSON a la API; devuelve la respuesta o lanza el error del servidor. */
function post(url, body = {}) {
  return api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

async function loadSummary() {
  const s = await api("/api/admin/security");
  document.getElementById("k-failed").textContent = s.failed_logins_24h;
  document.getElementById("k-failed-sub").textContent = `${s.lockouts_24h} bloqueo(s) de cuenta`;
  document.getElementById("k-locked").textContent = s.locked_accounts;
  document.getElementById("k-blocked").textContent = s.blocked_actions_24h;
  const chainOk = s.chain.ok;
  document.getElementById("k-chain").textContent = chainOk ? "Íntegra" : "ROTA";
  document.getElementById("k-chain-sub").textContent = chainOk
    ? `${s.chain.total} registros · último hash ${s.chain.last_hash.slice(0, 12)}…`
    : `rota en el registro #${s.chain.broken_at}`;
  document.getElementById("kpi-chain").className = `kpi ${chainOk ? "kpi-ok" : "kpi-crit"}`;

  const dl = document.getElementById("params");
  dl.replaceChildren();
  for (const [k, v] of s.parameters) dl.append(el("dt", k), el("dd", v));

  const tb = document.getElementById("tbl-recent");
  tb.replaceChildren();
  for (const a of s.recent) {
    const res = el("td"); res.append(el("span", a.result, `tag ${RESULT_CLS[a.result] || ""}`));
    const tr = el("tr");
    tr.append(el("td", fmtDate(a.ts), "small"), el("td", a.actor, "small"),
              el("td", a.action, "mono small"), el("td", a.detail || "—", "msg small"), res);
    tb.append(tr);
  }
}

function actionButton(label, handler, { danger = false, disabled = false, title = "" } = {}) {
  const b = el("button", label, `btn sm${danger ? " danger" : ""}`);
  b.type = "button";
  b.disabled = disabled;
  if (title) b.title = title;
  b.onclick = async () => {
    try { await handler(); toast("Cambio guardado y auditado"); await refresh(); }
    catch (err) { toast(err.message, "err"); }
  };
  return b;
}

async function loadUsers() {
  const users = await api("/api/admin/users");
  const tb = document.getElementById("tbl-users");
  tb.replaceChildren();
  for (const u of users) {
    const self = me && u.username === me.username;
    const tr = el("tr");

    const name = el("td", u.full_name || "—");
    const role = el("td");
    const sel = el("select");
    for (const [value, label] of Object.entries(ROLE_LABEL)) {
      const o = el("option", label); o.value = value; o.selected = value === u.role; sel.append(o);
    }
    sel.disabled = self;
    sel.title = self ? "No puede cambiar su propio rol" : "Cambiar rol";
    sel.onchange = async () => {
      try { await post(`/api/admin/users/${u.id}/role`, { role: sel.value }); toast("Rol actualizado y auditado"); }
      catch (err) { toast(err.message, "err"); }
      await refresh();
    };
    role.append(sel);

    const state = el("td");
    state.append(el("span", u.active ? "activo" : "desactivado", `tag ${u.active ? "ok" : "bad"}`));
    if (u.locked) {
      // Corrección 8.3: se muestra hasta cuándo dura el bloqueo
      const until = new Date(u.locked_until).toLocaleTimeString("es-CO", { hour: "numeric", minute: "2-digit" });
      state.append(" ", el("span", `bloqueado hasta ${until}`, "tag warn"));
    }
    if (self) state.append(" ", el("span", "usted", "tag dup"));

    const actions = el("td", "", "row-actions");
    actions.append(
      actionButton("Renombrar", async () => {
        const n = prompt(`Nombre visible de ${u.username}:`, u.full_name || "");
        if (n !== null) await post(`/api/admin/users/${u.id}/name`, { full_name: n });
      }),
      passwordButton(u),
      actionButton("Desbloquear", () => post(`/api/admin/users/${u.id}/unlock`), { disabled: !u.locked }),
      actionButton(u.active ? "Desactivar" : "Activar",
                   () => post(`/api/admin/users/${u.id}/active`, { active: !u.active }),
                   { danger: u.active, disabled: self && u.active,
                     title: self ? "No puede desactivar su propia cuenta" : "" }),
    );
    tr.append(el("td", u.username, "mono"), name, role, state, el("td", u.failed_attempts),
              el("td", fmtDate(u.last_login_at), "small"), actions);
    tb.append(tr);
  }
}

async function refresh() {
  await Promise.all([loadSummary(), loadUsers()]);
}

/* ---- Crear usuario ---- */
const dlgUser = document.getElementById("dlg-user");
document.getElementById("btn-new-user").onclick = () => {
  document.getElementById("frm-user").reset();
  document.getElementById("user-errors").replaceChildren();
  dlgUser.showModal();
};
document.getElementById("btn-cancel-user").onclick = () => dlgUser.close();
document.getElementById("frm-user").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const data = Object.fromEntries(new FormData(ev.target));
  try {
    await post("/api/admin/users", data);
    dlgUser.close();
    toast(`Usuario ${data.username} creado y auditado`);
    await refresh();
  } catch (err) {
    document.getElementById("user-errors").replaceChildren(...err.message.split("\n").map(m => el("li", m)));
  }
});

/* ---- Restablecer contraseña ---- */
const dlgPass = document.getElementById("dlg-pass");
let passTarget = null;
/** Botón que solo ABRE la ventana; el cambio se guarda al enviar el formulario. */
function passwordButton(u) {
  const b = el("button", "Contraseña", "btn sm");
  b.type = "button";
  b.onclick = () => {
    passTarget = u;
    document.getElementById("pass-user").textContent = u.username;
    document.getElementById("frm-pass").reset();
    document.getElementById("pass-errors").replaceChildren();
    dlgPass.showModal();
  };
  return b;
}
document.getElementById("btn-cancel-pass").onclick = () => dlgPass.close();
document.getElementById("frm-pass").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    await post(`/api/admin/users/${passTarget.id}/password`, Object.fromEntries(new FormData(ev.target)));
    dlgPass.close();
    toast(`Contraseña de ${passTarget.username} restablecida (auditado, sin mostrar la clave)`);
    await refresh();
  } catch (err) {
    document.getElementById("pass-errors").replaceChildren(...err.message.split("\n").map(m => el("li", m)));
  }
});

/* Fase 11: avisos por Telegram */
const NT_MODE = { telegram: ["Telegram activo", "ok"], simulado: ["Modo simulado (sin enviar)", "warn"],
                  apagado: ["Apagado", "bad"] };
const NT_STATUS = { enviado: "ok", simulado: "warn", agrupado: "", limitado: "warn", fallido: "bad", pendiente: "" };

async function loadNotify() {
  const st = await api("/api/notifications/status");
  const p = document.getElementById("nt-status");
  const [label, cls] = NT_MODE[st.mode];
  p.replaceChildren(el("span", label, `tag ${cls}`), " ",
    el("span", st.mode === "apagado" ? "Configure TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env (o NOTIFY_SIMULATE=1)"
      : `destino ${st.chat || "—"} · incidentes de severidad ${st.min_severity} (${st.min_severity_name}) o más ` +
        `graves · agrupa ${st.group_minutes} min · máx. ${st.max_per_minute}/min`, "small"));
  document.getElementById("btn-nt-test").disabled = st.mode === "apagado";
  const rows = await api("/api/notifications");
  const tb = document.getElementById("tbl-notify");
  tb.replaceChildren(...rows.map(n => {
    const tr = el("tr");
    const s = el("td"); s.append(el("span", n.status, `tag ${NT_STATUS[n.status] || ""}`));
    const txt = el("td", n.text, "msg small notify-text");
    if (n.error) txt.append(el("div", n.error, "muted small"));
    tr.append(el("td", n.id, "mono small"), el("td", fmtDate(n.created_at), "small"), el("td", n.kind),
              el("td", n.severity ?? "—", "mono"), s, txt);
    return tr;
  }));
  if (!rows.length) {
    const tr = el("tr"); const td = el("td", "Sin avisos todavía.", "muted"); td.colSpan = 6; tr.append(td); tb.append(tr);
  }
}
document.getElementById("btn-nt-test").onclick = async () => {
  try {
    const r = await post("/api/notifications/test");
    toast(`Aviso de prueba: ${r.status}`);
  } catch (err) { toast(err.message, "err"); }
  await loadNotify().catch(() => {});
};

document.getElementById("btn-refresh").onclick = () => refresh().catch(e => toast(e.message, "err"));

api("/api/auth/me").then(u => { me = u; return refresh(); }).catch(err => toast(err.message, "err"));
loadNotify().catch(err => toast(err.message, "err"));
