/*
 * Fase 10.2: solicitudes de cambio con matriz de riesgo, rollback y ventana.
 * Consume /api/changes. Los comandos se muestran con textContent (son datos).
 */
const section = document.getElementById("changes");
const CAN_EDIT = section.dataset.canEdit === "1";
const ME = section.dataset.user;
const IS_ADMIN = section.dataset.role === "admin_seguridad";
const OFFSET_H = -5;                       // hora de Colombia (igual que LOCAL_UTC_OFFSET)
const STATUS = {
  borrador: "Borrador", pendiente: "Pendiente de aprobación", aprobado: "Aprobado", rechazado: "Rechazado",
  en_ejecucion: "En ejecución", ejecutado: "Ejecutado", fallido: "Fallido", revertido: "Revertido",
  cancelado: "Cancelado",
};
const STATUS_TAG = { borrador: "", pendiente: "warn", aprobado: "ok", rechazado: "bad", en_ejecucion: "warn",
                     ejecutado: "ok", fallido: "bad", revertido: "bad", cancelado: "" };
const LEVEL = { 1: "bajo", 2: "medio", 3: "alto" };
const PROB = { 1: "improbable", 2: "posible", 3: "probable" };
let estado = "activos";
let current = null;          // cambio abierto en el detalle
let editingId = null;        // id del borrador que se edita (null = nuevo)

const levelOf = (score) => (score <= 2 ? "bajo" : score <= 4 ? "medio" : "alto");
const riskTag = (level, score) => el("span", `${level}${score ? ` (${score})` : ""}`, `tag risk-${level}`);

/** Fecha UTC -> valor de <input type="datetime-local"> en hora de Colombia. */
function toLocalInput(iso) {
  if (!iso) return "";
  return new Date(Date.parse(iso) + OFFSET_H * 3600e3).toISOString().slice(0, 16);
}
function windowText(c) {
  if (!c.window_start) return "Sin ventana (riesgo bajo)";
  return `${fmtDate(c.window_start)} → ${fmtDate(c.window_end)}`;
}

/** Matriz 3x3: filas = impacto (alto arriba), columnas = probabilidad. Marca la celda del cambio. */
function renderMatrix(box, impact, probability) {
  const t = el("table", "", "risk-matrix");
  const head = document.createElement("tr");
  head.append(el("th", "Impacto \\ Prob."));
  for (const p of [1, 2, 3]) head.append(el("th", PROB[p]));
  t.append(head);
  for (const i of [3, 2, 1]) {
    const tr = document.createElement("tr");
    tr.append(el("th", LEVEL[i]));
    for (const p of [1, 2, 3]) {
      const score = i * p;
      const td = el("td", score, `lvl-${levelOf(score)}${i === impact && p === probability ? " selected" : ""}`);
      tr.append(td);
    }
    t.append(tr);
  }
  box.replaceChildren(t);
}

/* ------------------------------ Lista ------------------------------ */
async function loadList() {
  const list = await api(`/api/changes?estado=${estado}`);
  const tb = document.getElementById("tbl-changes");
  tb.replaceChildren();
  for (const c of list) {
    const tr = el("tr", "", "clickable");
    const risk = el("td"); risk.append(riskTag(c.risk_level, c.risk_score));
    const st = el("td"); st.append(el("span", STATUS[c.status] || c.status, `tag ${STATUS_TAG[c.status] || ""}`));
    tr.append(el("td", c.id, "mono small"), el("td", c.title), el("td", c.device_name), risk, st,
              el("td", c.window_start ? windowText(c) : "—", "small"), el("td", c.requested_by),
              el("td", fmtDate(c.updated_at), "small"));
    tr.onclick = () => openDetail(c.id);
    tb.append(tr);
  }
  if (!list.length) {
    const tr = document.createElement("tr");
    const td = el("td", "No hay cambios en esta vista.", "muted"); td.colSpan = 8; tr.append(td); tb.append(tr);
  }
  document.getElementById("ch-count").textContent = `${list.length} cambios · clic en una fila para ver el detalle`;
}
for (const tab of document.querySelectorAll(".tab")) {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t === tab));
    estado = tab.dataset.estado;
    loadList().catch(err => toast(err.message, "err"));
  };
}

/* ---------------------------- Formulario ---------------------------- */
const dlgForm = document.getElementById("dlg-form");
const frm = document.getElementById("frm-change");
const FIELDS = ["device_id", "title", "reason", "commands", "rollback", "verify", "impact", "probability",
                "window_start", "window_end"];

function formData() {
  const data = {};
  for (const f of FIELDS) data[f] = frm.elements[f].value;
  return data;
}

async function loadDeviceOptions(selected) {
  const devices = await api("/api/devices");
  const sel = document.getElementById("f-device");
  sel.replaceChildren(new Option("— elija un equipo Cisco con conexión —", ""));
  for (const d of devices.filter(x => x.vendor === "Cisco" && x.connection_mode !== "ninguno")) {
    sel.append(new Option(`${d.name} (${d.connection_mode})`, d.id));
  }
  if (selected) sel.value = selected;
}

let assessTimer = null;
async function assess() {
  try {
    const res = await fetch("/api/changes/assess", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(formData()),
    });
    const { assessment: a } = await res.json();
    renderMatrix(document.getElementById("f-matrix"), Math.max(a.impact, a.min_impact), a.probability);
    const p = document.getElementById("f-risk");
    p.replaceChildren(riskTag(a.risk_level, a.risk_score), " ",
                      el("span", `${a.approvals_required} aprobación(es)` +
                                 (a.approvals_required > 1 ? " de personas distintas" : "") +
                                 ` · ventana ${a.window_required ? "obligatoria" : "opcional"}`, "small"));
    const reasons = document.getElementById("f-reasons");
    reasons.replaceChildren();
    if (a.min_impact > 1) reasons.append(el("li", `Impacto mínimo por los comandos: ${a.min_impact_name}`));
    for (const r of a.reasons) reasons.append(el("li", r));
  } catch (_) { /* la evaluación es solo una ayuda: el servidor valida al guardar */ }
}
frm.addEventListener("input", () => { clearTimeout(assessTimer); assessTimer = setTimeout(assess, 400); });

async function openForm(change = null) {
  frm.reset();
  editingId = change ? change.id : null;
  document.getElementById("f-title").textContent =
    change ? `Editar borrador #${change.id}` : "Nueva solicitud de cambio";
  document.getElementById("f-errors").replaceChildren();
  await loadDeviceOptions(change && change.device_id);
  if (change) {
    for (const f of FIELDS) {
      if (f === "device_id") continue;
      frm.elements[f].value = f.startsWith("window_") ? toLocalInput(change[f]) : (change[f] ?? "");
    }
  }
  await assess();
  dlgForm.showModal();
}

frm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const andSubmit = ev.submitter && ev.submitter.value === "submit";
  const errs = document.getElementById("f-errors");
  errs.replaceChildren();
  try {
    const res = await fetch(editingId ? `/api/changes/${editingId}` : "/api/changes", {
      method: editingId ? "PUT" : "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(formData()),
    });
    const body = await res.json();
    if (!res.ok) { errs.replaceChildren(...(body.errors || []).map(m => el("li", m))); return; }
    let id = body.id, warnings = [];
    if (andSubmit) {
      const r2 = await fetch(`/api/changes/${id}/submit`, { method: "POST" });
      const b2 = await r2.json();
      if (!r2.ok) {
        toast("Se guardó el borrador, pero no se pudo enviar", "err");
        dlgForm.close();
        await loadList();
        await openDetail(id, b2.errors || []);
        return;
      }
      warnings = b2.warnings || [];
    }
    dlgForm.close();
    toast(andSubmit ? `Cambio #${id} enviado a aprobación` : `Borrador #${id} guardado`);
    await loadList();
    await openDetail(id, [], warnings);
  } catch (err) { toast(err.message, "err"); }
});
document.getElementById("btn-form-close").onclick = () => dlgForm.close();
if (CAN_EDIT) document.getElementById("btn-new").onclick = () => openForm().catch(err => toast(err.message, "err"));

/* ------------------------------ Detalle ------------------------------ */
const dlgDetail = document.getElementById("dlg-detail");

async function openDetail(id, errors = [], extraWarnings = []) {
  const c = await api(`/api/changes/${id}`);
  current = c;
  document.getElementById("d-title").textContent = `#${c.id} · ${c.title}`;
  document.getElementById("d-badges").replaceChildren(
    riskTag(c.risk_level, c.risk_score), " ",
    el("span", STATUS[c.status] || c.status, `tag ${STATUS_TAG[c.status] || ""}`), " ",
    el("span", `${c.approvals_required} aprobación(es) requerida(s)`, "tag"));
  document.getElementById("d-warnings").replaceChildren(
    ...[...extraWarnings, ...c.warnings].filter((w, i, a) => a.indexOf(w) === i).map(w => el("li", w)));
  const info = document.getElementById("d-info");
  info.replaceChildren();
  const rows = [
    ["Equipo", c.device_name], ["Justificación", c.reason],
    ["Impacto · probabilidad", `${LEVEL[c.impact]} · ${PROB[c.probability]}` +
                               (c.min_impact > c.impact ? ` (mínimo impuesto: ${LEVEL[c.min_impact]})` : "")],
    ["Ventana", windowText(c)],
    ["Solicitó", `${c.requested_by} · ${fmtDate(c.created_at)}`],
  ];
  if (c.submitted_at) rows.push(["Enviado a aprobación", fmtDate(c.submitted_at)]);
  if (c.submitted_at) rows.push(["Línea base", c.baseline ? `v${c.baseline.version_no} · ${fmtDate(c.baseline.captured_at)}`
                                                           : "sin versión de configuración"]);
  if (c.cancel_reason) rows.push(["Cancelado", `${fmtDate(c.closed_at)} · ${c.cancel_reason}`]);
  for (const [k, v] of rows) info.append(el("dt", k), el("dd", v));
  renderMatrix(document.getElementById("d-matrix"), Math.max(c.impact, c.min_impact), c.probability);
  document.getElementById("d-reasons").replaceChildren(...c.risk_reasons.map(r => el("li", r)));
  document.getElementById("d-commands").textContent = c.commands;
  document.getElementById("d-rollback").textContent = c.rollback;
  document.getElementById("d-verify").textContent = c.verify || "(sin comandos de verificación)";

  const mine = c.requested_by === ME;
  document.getElementById("d-actions").hidden = !(CAN_EDIT && mine && c.status === "borrador");
  document.getElementById("frm-cancel").hidden =
    !(CAN_EDIT && (mine || IS_ADMIN) && ["borrador", "pendiente", "aprobado"].includes(c.status));
  document.getElementById("frm-cancel").reset();
  document.getElementById("d-errors").replaceChildren(...errors.map(m => el("li", m)));
  renderExecution(c, mine);
  if (!dlgDetail.open) dlgDetail.showModal();
}

/* -------------------- Fase 10.3: revisión, ejecución y rollback -------------------- */
function renderExecution(c, mine) {
  const approved = c.approvals.filter(a => a.decision === "aprobado").length;
  document.getElementById("d-appr-count").textContent =
    `· ${approved} de ${c.approvals_required} aprobación(es)`;
  const ol = document.getElementById("d-approvals");
  ol.replaceChildren(...c.approvals.map(a => {
    const li = el("li");
    li.append(el("span", `${fmtDate(a.decided_at)} · ${a.reviewer} `, "muted small"),
              el("span", a.decision, `tag ${a.decision === "aprobado" ? "ok" : "bad"}`), el("div", a.comment));
    return li;
  }));
  if (!c.approvals.length) ol.append(el("li", c.status === "borrador" ? "Aún no se ha enviado a aprobación."
                                                                    : "Sin revisiones todavía.", "muted small"));
  // Revisa un administrador de seguridad que no pidió el cambio y que no lo haya revisado ya
  const reviewed = c.approvals.some(a => a.reviewer === ME);
  const frmReview = document.getElementById("frm-review");
  frmReview.hidden = !(IS_ADMIN && !mine && !reviewed && c.status === "pendiente");
  frmReview.reset();

  const now = Date.now();
  const inWindow = !c.window_start || (now >= Date.parse(c.window_start) && now <= Date.parse(c.window_end));
  document.getElementById("d-exec-box").hidden = !(CAN_EDIT && c.status === "aprobado");
  document.getElementById("d-exec-window").textContent = !c.window_start ? "Sin ventana: se puede ejecutar ya." :
    inWindow ? `Dentro de la ventana (${windowText(c)}).` : `Fuera de la ventana (${windowText(c)}): el NOC no lo ejecutará.`;
  document.getElementById("btn-execute").disabled = !inWindow;

  const res = document.getElementById("d-result");
  res.replaceChildren();
  if (c.result) {
    const good = c.status === "ejecutado";
    res.append(el("span", STATUS[c.status], `tag ${good ? "ok" : "bad"}`), " ", el("strong", c.result));
    if (c.executed_by) res.append(el("span", ` · ${c.executed_by} · ${fmtDate(c.executed_at)}`, "muted small"));
  }
  document.getElementById("d-steps").replaceChildren(...c.execution.map(s => {
    const li = el("li", "", s.ok ? "ok" : "bad");
    li.append(el("span", s.ok ? "✓" : "✗", "step-mark"), el("strong", s.step), " ", el("span", s.detail, "small"));
    return li;
  }));
  const btnDiff = document.getElementById("btn-diff");
  btnDiff.hidden = !(c.pre_version_id && c.post_version_id && c.pre_version_id !== c.post_version_id);
  document.getElementById("d-diff").replaceChildren();
  const frmRb = document.getElementById("frm-rollback");
  frmRb.hidden = !(CAN_EDIT && c.status === "ejecutado");
  frmRb.reset();
}

function renderDiff(r) {
  const box = document.getElementById("d-diff");
  const head = el("p", "", "diag-summary");
  head.append(el("strong", `v${r.from.version_no} → v${r.to.version_no}`), " ",
              el("span", `+${r.added}`, "diff-plus mono"), " ", el("span", `−${r.removed}`, "diff-minus mono"));
  const pre = el("pre", "", "cmd-out diff");
  for (const line of r.lines) {
    let cls = "";
    if (line.startsWith("+++") || line.startsWith("---")) cls = "d-file";
    else if (line.startsWith("@@")) cls = "d-hunk";
    else if (line.startsWith("+")) cls = "d-add";
    else if (line.startsWith("-")) cls = "d-del";
    pre.append(el("span", line + "\n", cls));
  }
  box.replaceChildren(head, pre);
}

document.getElementById("btn-diff").onclick = async () => {
  try {
    renderDiff(await api(`/api/configs/diff?from=${current.pre_version_id}&to=${current.post_version_id}`));
  } catch (err) { toast(err.message, "err"); }
};

document.getElementById("frm-review").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const res = await fetch(`/api/changes/${current.id}/review`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision: ev.submitter.value, comment: ev.target.elements.comment.value.trim() }),
  });
  const body = await res.json();
  if (!res.ok) { document.getElementById("d-errors").replaceChildren(...body.errors.map(m => el("li", m))); return; }
  toast(ev.submitter.value === "aprobar" ? "Revisión registrada: aprobado" : "Cambio rechazado");
  await loadList();
  await openDetail(current.id);
});

document.getElementById("btn-execute").onclick = async () => {
  const btn = document.getElementById("btn-execute");
  btn.disabled = true; btn.textContent = "Ejecutando… (línea base, aplicar, verificar)";
  document.getElementById("d-errors").replaceChildren();
  try {
    const res = await fetch(`/api/changes/${current.id}/execute`, { method: "POST" });
    const body = await res.json();
    if (body.errors) document.getElementById("d-errors").replaceChildren(...body.errors.map(m => el("li", m)));
    if (res.ok) toast(body.status === "ejecutado" ? "Cambio ejecutado y verificado" : `Resultado: ${STATUS[body.status]}`,
                      body.status === "ejecutado" ? "ok" : "err");
    await loadList();
    const errs = body.errors || [];
    await openDetail(current.id, errs);
  } catch (err) { toast(err.message, "err"); }
  finally { btn.textContent = "Ejecutar cambio ahora"; }
};

document.getElementById("frm-rollback").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = ev.target.querySelector("button");
  btn.disabled = true;
  try {
    const res = await fetch(`/api/changes/${current.id}/rollback`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comment: ev.target.elements.comment.value.trim() }),
    });
    const body = await res.json();
    if (!res.ok) { document.getElementById("d-errors").replaceChildren(...body.errors.map(m => el("li", m))); return; }
    toast(`Cambio #${current.id}: ${STATUS[body.status]}`, body.status === "revertido" ? "ok" : "err");
    await loadList();
    await openDetail(current.id);
  } catch (err) { toast(err.message, "err"); }
  finally { btn.disabled = false; }
});

document.getElementById("btn-detail-close").onclick = () => dlgDetail.close();
document.getElementById("btn-edit").onclick = () => { dlgDetail.close(); openForm(current); };
document.getElementById("btn-submit").onclick = async () => {
  const res = await fetch(`/api/changes/${current.id}/submit`, { method: "POST" });
  const body = await res.json();
  if (!res.ok) { document.getElementById("d-errors").replaceChildren(...body.errors.map(m => el("li", m))); return; }
  toast(`Cambio #${current.id} enviado a aprobación`);
  await loadList();
  await openDetail(current.id, [], body.warnings || []);
};
document.getElementById("frm-cancel").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const res = await fetch(`/api/changes/${current.id}/cancel`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: ev.target.elements.reason.value.trim() }),
  });
  const body = await res.json();
  if (!res.ok) { document.getElementById("d-errors").replaceChildren(...body.errors.map(m => el("li", m))); return; }
  toast(`Cambio #${current.id} cancelado`);
  await loadList();
  await openDetail(current.id);
});

loadList().catch(err => toast(err.message, "err"));
