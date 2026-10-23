/*
 * Página de inventario: listar, crear, editar y eliminar equipos
 * usando la API /api/devices.
 */
const tbody = document.querySelector("#tbl-devices tbody");
const dlg = document.getElementById("dlg-device");
const frm = document.getElementById("frm-device");
const errorsBox = document.getElementById("frm-errors");
let devices = [];
// Fase 8.4: el servidor indica si el rol puede cambiar datos (el auditor no)
const CAN_EDIT = document.getElementById("inventory").dataset.canEdit === "1";

async function loadDevices() {
  devices = await api("/api/devices");
  tbody.replaceChildren();
  for (const d of devices) {
    const tr = document.createElement("tr");
    const name = el("td");
    name.append(el("strong", d.name));
    if (d.is_simulated) name.append(" ", el("span", "SIM", "tag sim"));
    tr.append(
      name,
      el("td", d.ip, "mono"),
      el("td", d.vendor),
      el("td", d.model || "—"),
      el("td", d.version || "—"),
      el("td", d.location || "—"),
    );
    const st = el("td"); st.append(el("span", d.status, `status st-${d.status}`)); tr.append(st);
    const src = el("td");
    src.append(d.authorized ? el("span", "autorizada", "tag ok") : el("span", "NO autorizada", "tag bad"));
    const ifc = el("td");
    const bIf = el("button", `Ver (${d.interface_count ?? 0})`, "btn sm");
    bIf.onclick = () => openInterfaces(d);
    ifc.append(bIf);
    // Fase 9.1: conexión con el equipo (sesiones y trazabilidad)
    const cnc = el("td");
    const bCn = el("button", d.connection_mode === "ninguno" ? "—" : d.connection_mode, "btn sm");
    bCn.title = "Conexión, identificación del equipo físico e historial de sesiones";
    bCn.onclick = () => openConnection(d);
    cnc.append(bCn);
    // Fase 10.1: versiones de configuración (en la misma celda, para no ensanchar la tabla)
    if (d.connection_mode !== "ninguno" || d.config_count) {
      const bCf = el("button", d.config_count ? `Config. v${d.config_count}` : "Config.", "btn sm cfg-btn");
      bCf.title = "Versiones de configuración y diferencias";
      bCf.onclick = () => openConfigs(d);
      cnc.append(bCf);
    }
    tr.append(src, ifc, cnc, el("td", fmtDate(d.updated_at), "small"));

    const actions = el("td", "", "row-actions");
    if (CAN_EDIT) {
      const bEdit = el("button", "Editar", "btn sm");
      bEdit.onclick = () => openForm(d);
      const bDel = el("button", "Eliminar", "btn sm danger");
      bDel.onclick = () => removeDevice(d);
      actions.append(bEdit, bDel);
    }
    tr.append(actions);
    tbody.append(tr);
  }
  document.getElementById("devices-count").textContent =
    `${devices.length} equipos · ${devices.filter(d => d.authorized).length} fuentes autorizadas`;
}

function openForm(device = null) {
  frm.reset();
  errorsBox.replaceChildren();
  document.getElementById("dlg-title").textContent = device ? `Editar ${device.name}` : "Nuevo equipo";
  frm.elements.id.value = device ? device.id : "";
  if (device) {
    for (const f of ["name", "ip", "vendor", "status", "model", "version", "location",
                     "connection_mode", "platform", "console_port"]) {
      frm.elements[f].value = device[f] ?? "";
    }
    frm.elements.authorized.checked = !!device.authorized;
    frm.elements.is_simulated.checked = !!device.is_simulated;
  }
  dlg.showModal();
}

frm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const id = frm.elements.id.value;
  const data = {};
  for (const f of ["name", "ip", "vendor", "status", "model", "version", "location",
                   "connection_mode", "platform", "console_port"]) {
    data[f] = frm.elements[f].value.trim();
  }
  data.authorized = frm.elements.authorized.checked;
  data.is_simulated = frm.elements.is_simulated.checked;
  try {
    await api(id ? `/api/devices/${id}` : "/api/devices", {
      method: id ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    dlg.close();
    toast(id ? "Equipo actualizado" : "Equipo creado");
    loadDevices();
  } catch (err) {
    // Los errores de validación del servidor se muestran en el formulario
    errorsBox.replaceChildren(...err.message.split("\n").map(m => el("li", m)));
  }
});

async function removeDevice(d) {
  if (!confirm(`¿Eliminar ${d.name} (${d.ip})?\nSus eventos se conservan para la trazabilidad;` +
               ` sus ${d.interface_count ?? 0} interfaces se eliminan.`)) return;
  try {
    await api(`/api/devices/${d.id}`, { method: "DELETE" });
    toast(`${d.name} eliminado`);
    loadDevices();
  } catch (err) { toast(err.message, "err"); }
}

/* ---------------------------------------------------------------------------
 * Fase 9.1: conexión con el equipo  (/api/devices/<id>/session)
 * Las salidas del equipo se muestran con textContent: son DATOS, nunca HTML.
 * ------------------------------------------------------------------------- */
const dlgCn = document.getElementById("dlg-conn");
const frmCn = document.getElementById("frm-conn");
const MODE_TEXT = {
  ninguno: "Sin conexión: el NOC solo recibe Syslog de este equipo.",
  simulado: "Modo simulado: respuestas de ejemplo con formato real (samples/cli). No hay red.",
  consola: "Modo consola (equipo prestado): cable de consola, sin contraseñas. Cierre PuTTY antes de conectar.",
  ssh: "Modo SSH (equipo fijo): credencial en .env; la llave SSH del equipo queda fijada.",
};
let cnDevice = null;

async function openConnection(d) {
  cnDevice = d;
  document.getElementById("cn-title").textContent = `Conexión con ${d.name}`;
  document.getElementById("cn-mode").textContent =
    MODE_TEXT[d.connection_mode] + (d.console_port ? ` Puerto: ${d.console_port}.` : "");
  for (const id of ["cn-errors", "cn-warnings", "cn-output"]) document.getElementById(id).replaceChildren();
  const sel = frmCn.elements.command;
  sel.replaceChildren(new Option("— solo identificar el equipo —", ""));
  frmCn.hidden = !CAN_EDIT || d.connection_mode === "ninguno";
  document.getElementById("frm-diag").hidden = frmCn.hidden;          // Fase 9.4
  document.getElementById("cn-diag").replaceChildren();
  if (!frmCn.hidden) {
    try {
      const a = await api(`/api/console/allowed?vendor=${encodeURIComponent(d.vendor)}`);
      for (const c of a.allowed) sel.append(new Option(`${c.command} — ${c.description}`, c.command));
    } catch (_) { /* sin lista: solo identificar */ }
  }
  showIdentity(d);
  await loadSessions();
  dlgCn.showModal();
}

function showIdentity(d) {
  const box = document.getElementById("cn-identity");
  box.replaceChildren();
  const items = [["N.º de serie", d.serial_number], ["Modelo detectado", d.detected_model],
                 ["Versión detectada", d.detected_version], ["Última identificación", fmtDate(d.last_identified_at)]];
  for (const [k, v] of items) {
    const div = el("div");
    div.append(el("span", k, "muted small"), el("strong", v || "—", "mono"));
    box.append(div);
  }
}

async function loadSessions() {
  const rows = await api(`/api/devices/${cnDevice.id}/sessions`);
  const tb = document.querySelector("#tbl-sessions tbody");
  tb.replaceChildren();
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.className = "clickable";
    const st = el("td"); st.append(el("span", r.status, `tag ${r.status === "cerrada" ? "ok" : "bad"}`));
    tr.append(el("td", r.id), el("td", fmtDate(r.started_at), "small"), el("td", r.transport),
              el("td", r.started_by), st, el("td", r.serial_number || "—", "mono"), el("td", r.commands_count));
    tr.onclick = () => showSession(r.id);
    tb.append(tr);
  }
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = el("td", "Sin sesiones todavía.", "muted"); td.colSpan = 7; tr.append(td); tb.append(tr);
  }
}

function renderSession(s) {
  document.getElementById("cn-warnings").replaceChildren(...(s.warnings || []).map(w => el("li", w)));
  const out = document.getElementById("cn-output");
  const where = s.target !== s.transport ? `${s.transport} ${s.target}` : s.transport;
  out.replaceChildren(el("p", `Sesión ${s.id} · ${where} · ${s.status} · por ${s.started_by}` +
                               (s.error ? ` · ${s.error}` : ""), "small muted"));
  for (const c of s.commands) {
    out.append(el("div", `${c.command}  ·  ${c.duration_ms} ms  ·  SHA-256 ${c.output_sha256.slice(0, 16)}…`, "cmd-head mono"));
    out.append(el("pre", c.output, "cmd-out"));
  }
}

async function showSession(id) {
  try { renderSession(await api(`/api/sessions/${id}`)); } catch (err) { toast(err.message, "err"); }
}

frmCn.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = document.getElementById("btn-cn-run");
  const cmd = frmCn.elements.command.value;
  document.getElementById("cn-errors").replaceChildren();
  btn.disabled = true; btn.textContent = "Conectando…";
  try {
    const res = await fetch(`/api/devices/${cnDevice.id}/session`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ commands: cmd ? [cmd] : [] }),
    });
    const body = await res.json();
    if (body.errors) document.getElementById("cn-errors").replaceChildren(...body.errors.map(m => el("li", m)));
    if (body.id) renderSession(body);
    await loadDevices();
    cnDevice = devices.find(x => x.id === cnDevice.id) || cnDevice;
    showIdentity(cnDevice);
    await loadSessions();
  } catch (err) { toast(err.message, "err"); }
  finally { btn.disabled = false; btn.textContent = "Conectar"; }
});
document.getElementById("btn-cn-close").onclick = () => dlgCn.close();

/* Fase 9.4: ping / traceroute ejecutado por el equipo (destino validado en el servidor) */
const frmDiag = document.getElementById("frm-diag");
frmDiag.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = document.getElementById("btn-diag");
  const box = document.getElementById("cn-diag");
  const errs = document.getElementById("cn-errors");
  errs.replaceChildren(); box.replaceChildren();
  btn.disabled = true; btn.textContent = "Ejecutando… (un traceroute puede tardar)";
  try {
    const res = await fetch(`/api/devices/${cnDevice.id}/diagnostic`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: frmDiag.elements.type.value, target: frmDiag.elements.target.value.trim() }),
    });
    const body = await res.json();
    if (!res.ok) {
      errs.replaceChildren(...(body.errors || [body.error]).map(m => el("li", m)));
    } else {
      const ok = body.type === "ping" ? body.result.reachable : body.result.reached;
      const head = el("p", "", "diag-summary");
      head.append(el("span", ok ? "OK" : "SIN RESPUESTA", `tag ${ok ? "ok" : "bad"}`), " ",
                  el("strong", body.summary), el("span", ` · sesión ${body.session}`, "muted small"));
      box.append(head);
      if (body.type === "traceroute" && body.result.hops.length) {
        const t = el("table", "", "hops");
        const hr = document.createElement("tr");
        for (const h of ["Salto", "IP", "Promedio"]) hr.append(el("th", h));
        t.append(hr);
        for (const h of body.result.hops) {
          const tr = document.createElement("tr");
          tr.append(el("td", h.hop), el("td", h.ip || "* (sin respuesta)", "mono"),
                    el("td", h.avg_ms !== null ? `${h.avg_ms} ms` : "—"));
          t.append(tr);
        }
        box.append(t);
      }
      box.append(el("div", body.command, "cmd-head mono"), el("pre", body.output, "cmd-out"));
    }
    await loadSessions();
  } catch (err) { toast(err.message, "err"); }
  finally { btn.disabled = false; btn.textContent = "Ejecutar desde el equipo"; }
});

/* ---------------------------------------------------------------------------
 * Fase 10.1: versiones de configuración  (/api/devices/<id>/configs, /api/configs/diff)
 * La configuración es un DATO: se muestra con textContent, nunca como HTML.
 * ------------------------------------------------------------------------- */
const dlgCf = document.getElementById("dlg-configs");
const frmCap = document.getElementById("frm-capture");
const frmDiff = document.getElementById("frm-diff");
let cfDevice = null;
let cfVersions = [];

async function openConfigs(d) {
  cfDevice = d;
  document.getElementById("cf-title").textContent = `Versiones de configuración · ${d.name}`;
  frmCap.hidden = !CAN_EDIT || d.connection_mode === "ninguno";
  for (const id of ["cf-errors", "cf-warnings", "cf-output"]) document.getElementById(id).replaceChildren();
  document.getElementById("cf-message").replaceChildren();
  frmCap.reset();
  await loadConfigs();
  dlgCf.showModal();
}

async function loadConfigs() {
  cfVersions = await api(`/api/devices/${cfDevice.id}/configs`);
  const tb = document.querySelector("#tbl-configs tbody");
  tb.replaceChildren();
  for (const v of cfVersions) {
    const tr = document.createElement("tr");
    const ch = el("td");
    if (v.added === null) ch.append(el("span", "inicial", "tag"));
    else ch.append(el("span", `+${v.added}`, "diff-plus mono"), " ", el("span", `−${v.removed}`, "diff-minus mono"));
    const view = el("td");
    const b = el("button", "Ver", "btn sm");
    b.onclick = () => showConfig(v.id);
    view.append(b);
    tr.append(el("td", `v${v.version_no}`, "mono"), el("td", fmtDate(v.captured_at), "small"),
              el("td", v.captured_by), el("td", v.serial_number || "—", "mono"), el("td", v.lines), ch,
              el("td", v.masked), el("td", v.note || "—", "small"), view);
    tb.append(tr);
  }
  if (!cfVersions.length) {
    const tr = document.createElement("tr");
    const td = el("td", "Sin versiones todavía: use «Leer y guardar configuración».", "muted");
    td.colSpan = 9; tr.append(td); tb.append(tr);
  }
  // Selectores para comparar: por defecto, la penúltima contra la última
  frmDiff.hidden = cfVersions.length < 2;
  for (const name of ["from", "to"]) {
    const sel = frmDiff.elements[name];
    sel.replaceChildren(...cfVersions.map(v => new Option(`v${v.version_no} · ${fmtDate(v.captured_at)}`, v.id)));
  }
  if (cfVersions.length >= 2) {
    frmDiff.elements.from.value = cfVersions[1].id;
    frmDiff.elements.to.value = cfVersions[0].id;
  }
}

async function showConfig(id) {
  try {
    const v = await api(`/api/configs/${id}`);
    const out = document.getElementById("cf-output");
    out.replaceChildren(
      el("div", `v${v.version_no} · ${v.command} · ${v.lines} líneas · SHA-256 ${v.sha256.slice(0, 16)}…`, "cmd-head mono"),
      el("pre", v.content, "cmd-out config-text"));
  } catch (err) { toast(err.message, "err"); }
}

function renderDiff(r) {
  const out = document.getElementById("cf-output");
  out.replaceChildren();
  document.getElementById("cf-warnings").replaceChildren(...(r.warnings || []).map(w => el("li", w)));
  if (r.identical) { out.append(el("p", "Las dos versiones son idénticas.", "muted")); return; }
  const head = el("p", "", "diag-summary");
  head.append(el("strong", `v${r.from.version_no} → v${r.to.version_no}`), " ",
              el("span", `+${r.added} agregadas`, "diff-plus mono"), " ",
              el("span", `−${r.removed} quitadas`, "diff-minus mono"));
  const pre = el("pre", "", "cmd-out diff");
  for (const line of r.lines) {
    let cls = "";
    if (line.startsWith("+++") || line.startsWith("---")) cls = "d-file";
    else if (line.startsWith("@@")) cls = "d-hunk";
    else if (line.startsWith("+")) cls = "d-add";
    else if (line.startsWith("-")) cls = "d-del";
    pre.append(el("span", line + "\n", cls));
  }
  out.append(head, pre);
  if (r.truncated) out.append(el("p", "Diferencia recortada: es muy larga.", "muted small"));
}

frmDiff.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    renderDiff(await api(`/api/configs/diff?from=${frmDiff.elements.from.value}&to=${frmDiff.elements.to.value}`));
  } catch (err) { toast(err.message, "err"); }
});

frmCap.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = document.getElementById("btn-capture");
  const errs = document.getElementById("cf-errors");
  const msg = document.getElementById("cf-message");
  errs.replaceChildren(); msg.replaceChildren();
  document.getElementById("cf-warnings").replaceChildren();
  btn.disabled = true; btn.textContent = "Leyendo el equipo…";
  try {
    const res = await fetch(`/api/devices/${cfDevice.id}/configs`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: frmCap.elements.note.value.trim() }),
    });
    const body = await res.json();
    if (body.errors) errs.replaceChildren(...body.errors.map(m => el("li", m)));
    if (body.version) {
      const alert = body.changed && body.previous;
      msg.replaceChildren(el("span", alert ? "CAMBIÓ" : body.changed ? "GUARDADA" : "SIN CAMBIOS",
                             `tag ${alert ? "bad" : "ok"}`), " ",
                          el("strong", body.message),
                          el("span", ` · ${body.masked} secretos ocultos · sesión ${body.session}`, "muted small"));
      document.getElementById("cf-warnings").replaceChildren(...body.warnings.map(w => el("li", w)));
      frmCap.reset();
      await loadConfigs();
      if (alert) renderDiff(await api(`/api/configs/diff?from=${body.previous.id}&to=${body.version.id}`));
      await loadDevices();
    }
  } catch (err) { toast(err.message, "err"); }
  finally { btn.disabled = false; btn.textContent = "Leer y guardar configuración"; }
});
document.getElementById("btn-cf-close").onclick = () => dlgCf.close();

/* ---------------------------------------------------------------------------
 * Fase 8.4: interfaces del equipo  (/api/devices/<id>/interfaces)
 * ------------------------------------------------------------------------- */
const dlgIf = document.getElementById("dlg-ifaces");
const frmIf = document.getElementById("frm-iface");
const ifErrors = document.getElementById("if-errors");
const ifBody = document.querySelector("#tbl-ifaces tbody");
const IF_STATUS_CLASS = { up: "ok", down: "bad", admin_down: "warn", desconocido: "" };
let currentDevice = null;

async function openInterfaces(d) {
  currentDevice = d;
  document.getElementById("if-title").textContent = `Interfaces de ${d.name} (${d.vendor})`;
  frmIf.hidden = !CAN_EDIT;
  // Fase 9.3: leer del equipo solo si el rol puede y el equipo tiene modo de conexión
  document.getElementById("if-sync").hidden = !CAN_EDIT || d.connection_mode === "ninguno";
  document.getElementById("if-sync-summary").replaceChildren();
  resetIfaceForm();
  await loadInterfaces();
  dlgIf.showModal();
}

async function loadInterfaces() {
  const data = await api(`/api/devices/${currentDevice.id}/interfaces`);
  document.getElementById("if-example").textContent = `Ejemplos para ${data.device.vendor}: ${data.example}`;
  ifBody.replaceChildren();
  for (const i of data.rows) {
    const tr = document.createElement("tr");
    const st = el("td"); st.append(el("span", i.status, `tag ${IF_STATUS_CLASS[i.status] || ""}`));
    const src = el("td"); src.append(el("span", i.source === "equipo" ? "equipo" : "manual",
                                        `tag ${i.source === "equipo" ? "dup" : ""}`));
    tr.append(el("td", i.name, "mono"), el("td", i.ip_address || "—", "mono"),
              el("td", i.description || "—"), st, src, el("td", fmtDate(i.updated_at), "small"));
    const act = el("td", "", "row-actions");
    if (CAN_EDIT) {
      const bE = el("button", "Editar", "btn sm");
      bE.onclick = () => editIface(i);
      const bD = el("button", "Eliminar", "btn sm danger");
      bD.onclick = () => removeIface(i);
      act.append(bE, bD);
    }
    tr.append(act);
    ifBody.append(tr);
  }
  if (!data.rows.length) {
    const tr = document.createElement("tr");
    const td = el("td", "Sin interfaces registradas: los eventos de este equipo no se comparan.", "muted");
    td.colSpan = 7; tr.append(td); ifBody.append(tr);
  }
  document.getElementById("if-count").textContent = `${data.rows.length} interfaces registradas`;
}

function resetIfaceForm() {
  frmIf.reset();
  frmIf.elements.iface_id.value = "";
  ifErrors.replaceChildren();
  document.getElementById("btn-if-save").textContent = "Agregar interfaz";
}

function editIface(i) {
  resetIfaceForm();
  frmIf.elements.iface_id.value = i.id;
  frmIf.elements.name.value = i.name;
  frmIf.elements.description.value = i.description || "";
  frmIf.elements.status.value = i.status;
  document.getElementById("btn-if-save").textContent = `Guardar cambios de ${i.name}`;
  frmIf.elements.name.focus();
}

frmIf.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const id = frmIf.elements.iface_id.value;
  const data = { name: frmIf.elements.name.value.trim(), status: frmIf.elements.status.value,
                 description: frmIf.elements.description.value.trim() };
  const base = `/api/devices/${currentDevice.id}/interfaces`;
  try {
    const saved = await api(id ? `${base}/${id}` : base, {
      method: id ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    toast(id ? `Interfaz ${saved.name} actualizada` : `Interfaz ${saved.name} registrada`);
    resetIfaceForm();
    await loadInterfaces();
    loadDevices();                      // actualiza el contador de la tabla
  } catch (err) {
    ifErrors.replaceChildren(...err.message.split("\n").map(m => el("li", m)));
  }
});

async function removeIface(i) {
  if (!confirm(`¿Eliminar la interfaz ${i.name} de ${currentDevice.name}?`)) return;
  try {
    await api(`/api/devices/${currentDevice.id}/interfaces/${i.id}`, { method: "DELETE" });
    toast(`Interfaz ${i.name} eliminada`);
    resetIfaceForm();
    await loadInterfaces();
    loadDevices();
  } catch (err) { toast(err.message, "err"); }
}

/* Fase 9.3: leer las interfaces reales (conecta, ejecuta y compara) */
const SYNC_LABELS = [["nuevas", "Nuevas"], ["actualizadas", "Cambiaron"], ["desaparecidas", "Ya no están en el equipo"],
                     ["eliminadas", "Eliminadas del inventario"], ["invalidas", "Rechazadas (nombre inválido)"]];
document.getElementById("btn-if-sync").onclick = async () => {
  const btn = document.getElementById("btn-if-sync");
  const box = document.getElementById("if-sync-summary");
  btn.disabled = true; btn.textContent = "Leyendo…";
  try {
    const res = await fetch(`/api/devices/${currentDevice.id}/interfaces/sync`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ remove_missing: document.getElementById("if-remove").checked }),
    });
    const body = await res.json();
    if (!res.ok) {
      box.replaceChildren(...(body.errors || [body.error]).map(m => el("li", m)));
    } else {
      const s = body.summary;
      const items = [el("li", `Sesión ${body.session} · equipo físico ${body.serial_number || "?"} · ` +
                              `${s.sin_cambios.length} sin cambios`)];
      for (const [k, label] of SYNC_LABELS) {
        if (s[k].length) items.push(el("li", `${label} (${s[k].length}): ${s[k].join(", ")}`));
      }
      for (const w of body.warnings || []) items.push(el("li", w));
      box.replaceChildren(...items);
      toast("Interfaces leídas del equipo");
    }
    await loadInterfaces();
    loadDevices();
  } catch (err) { toast(err.message, "err"); }
  finally { btn.disabled = false; btn.textContent = "Leer del equipo"; }
};

document.getElementById("btn-if-reset").onclick = resetIfaceForm;
document.getElementById("btn-if-close").onclick = () => dlgIf.close();

const btnNew = document.getElementById("btn-new");   // no existe para el auditor
if (btnNew) btnNew.onclick = () => openForm();
document.getElementById("btn-cancel").onclick = () => dlg.close();
loadDevices().catch(err => toast(err.message, "err"));
