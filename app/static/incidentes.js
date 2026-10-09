/*
 * Página de incidentes: lista por estado, detalle con seguimiento y acciones
 * (asignar, en progreso, nota, cerrar). Consume /api/incidents.
 */
const INC_LABEL = { abierto: "Abierto", asignado: "Asignado", en_progreso: "En progreso", cerrado: "Cerrado" };
const tbody = document.getElementById("tbl-incidents");
const dlg = document.getElementById("dlg-inc");
let estado = "abiertos";
let current = null;   // incidente abierto en la ventana de detalle

function incStatus(s) { return el("span", INC_LABEL[s] || s, `inc-status inc-${s}`); }

async function loadList() {
  const list = await api(`/api/incidents?estado=${estado}`);
  tbody.replaceChildren();
  for (const i of list) {
    const tr = el("tr", "", "clickable");
    const sev = el("td"); sev.append(severityBadge(i.severity));
    const title = el("td"); title.append(el("strong", i.title));
    if (i.created_by === "sistema") title.append(" ", el("span", "automático", "tag dup"));
    if (i.is_simulated) title.append(" ", el("span", "SIM", "tag sim"));
    const st = el("td"); st.append(incStatus(i.status));
    tr.append(el("td", i.id, "mono small"), sev, title, el("td", i.device_name || "—"), st,
              el("td", i.assigned_to || "—"), el("td", i.event_count, "mono"),
              el("td", fmtDate(i.created_at), "small"), el("td", fmtDate(i.updated_at), "small"));
    tr.onclick = () => openIncident(i.id);
    tbody.append(tr);
  }
  document.getElementById("inc-count").textContent = `${list.length} incidentes · clic en una fila para gestionarlo`;
}

async function openIncident(id) {
  const data = await api(`/api/incidents/${id}`);
  current = data.incident;
  const i = data.incident;
  document.getElementById("d-title").textContent = `#${i.id} · ${i.title}`;

  const badges = document.getElementById("d-badges");
  badges.replaceChildren(severityBadge(i.severity), " ", incStatus(i.status));
  if (i.created_by === "sistema") badges.append(" ", el("span", "creado automáticamente", "tag dup"));

  const info = document.getElementById("d-info");
  info.replaceChildren();
  const rows = [
    ["Equipo", i.device_name || "—"], ["Responsable", i.assigned_to || "sin asignar"],
    ["Descripción", i.description || "—"], ["Eventos correlacionados", i.event_count],
    ["Creado", `${fmtDate(i.created_at)} por ${i.created_by}`], ["Último evento", fmtDate(i.last_event_at)],
  ];
  if (i.status === "cerrado") rows.push(["Cerrado", fmtDate(i.closed_at)], ["Resolución", i.resolution]);
  for (const [k, v] of rows) info.append(el("dt", k), el("dd", v));

  // Evento origen: el mensaje crudo se muestra como TEXTO (dato no confiable)
  const evBox = document.getElementById("d-event");
  evBox.hidden = !data.event;
  if (data.event) document.getElementById("d-event-raw").textContent = data.event.raw;

  // Acciones según el estado (las mismas reglas las valida el servidor)
  const closed = i.status === "cerrado";
  document.getElementById("d-actions").hidden = closed;
  document.getElementById("d-closed-msg").hidden = !closed;
  document.getElementById("btn-progress").disabled = !data.allowed.includes("en_progreso");
  document.getElementById("in-assign").value = i.assigned_to || "";
  document.getElementById("d-errors").replaceChildren();

  const ol = document.getElementById("d-notes");
  ol.replaceChildren();
  for (const n of data.notes) {
    const li = el("li");
    li.append(el("span", `${fmtDate(n.created_at)} · ${n.author}`, "muted small"), el("div", n.note));
    ol.append(li);
  }
  document.getElementById("btn-suggest").hidden = closed;
  await loadProposals(i.id, closed);
  if (location.hash !== `#${i.id}`) history.replaceState(null, "", `#${i.id}`);
  if (!dlg.open) dlg.showModal();
}

/** Ejecuta una acción sobre el incidente actual y refresca la vista. */
async function act(path, body, okMsg) {
  try {
    await api(`/api/incidents/${current.id}/${path}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    toast(okMsg);
    await openIncident(current.id);
    loadList();
    return true;
  } catch (err) {
    document.getElementById("d-errors").replaceChildren(...err.message.split("\n").map(m => el("li", m)));
    return false;
  }
}

document.getElementById("frm-assign").addEventListener("submit", (e) => {
  e.preventDefault();
  act("assign", { assigned_to: e.target.assigned_to.value.trim() }, "Responsable asignado");
});
document.getElementById("frm-progress").addEventListener("submit", (e) => {
  e.preventDefault();
  act("status", { status: "en_progreso" }, "Incidente en progreso");
});
document.getElementById("frm-note").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (await act("notes", { note: e.target.note.value.trim() }, "Nota agregada")) e.target.reset();
});
document.getElementById("frm-closeinc").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (await act("status", { status: "cerrado", resolution: e.target.resolution.value.trim() }, "Incidente cerrado")) e.target.reset();
});
document.getElementById("btn-close-inc").onclick = () => { dlg.close(); history.replaceState(null, "", location.pathname); };

// Pestañas Abiertos / Cerrados / Todos
for (const tab of document.querySelectorAll(".tab")) {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t === tab));
    estado = tab.dataset.estado;
    loadList();
  };
}

// Nuevo incidente manual
const dlgNew = document.getElementById("dlg-new");
document.getElementById("btn-new").onclick = async () => {
  const sel = document.getElementById("new-device");
  if (sel.options.length === 1) {
    for (const d of await api("/api/devices")) { const o = el("option", `${d.name} (${d.ip})`); o.value = d.id; sel.append(o); }
  }
  document.getElementById("frm-new").reset();
  document.getElementById("new-errors").replaceChildren();
  dlgNew.showModal();
};
document.getElementById("btn-cancel-new").onclick = () => dlgNew.close();
document.getElementById("frm-new").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    const inc = await api("/api/incidents", {
      method: "POST", headers: { "Content-Type": "application/json" },
      // f.elements["title"]: "f.title" devolvería el atributo title del formulario, no el campo
      body: JSON.stringify({ title: f.elements["title"].value.trim(), severity: f.elements["severity"].value,
                             device_id: f.elements["device_id"].value || null,
                             description: f.elements["description"].value.trim() }),
    });
    dlgNew.close();
    toast(`Incidente #${inc.id} creado`);
    loadList();
  } catch (err) {
    document.getElementById("new-errors").replaceChildren(...err.message.split("\n").map(m => el("li", m)));
  }
});

// Abrir directamente /incidentes#12 (enlace desde el dashboard o desde eventos).
// "hashchange" cubre el caso en que ya se está en la página y solo cambia el #.
function openFromHash() {
  const id = parseInt(location.hash.slice(1), 10);
  if (id && (!current || current.id !== id || !dlg.open)) openIncident(id).catch(err => toast(err.message, "err"));
}
window.addEventListener("hashchange", openFromHash);
loadList().then(openFromHash).catch(err => toast(err.message, "err"));


/* ---------------- Propuestas de acción (flujo seguro) ---------------- */
const P_LABEL = { pendiente: "Pendiente de revisión", aprobada: "Aprobada", rechazada: "Rechazada",
                  ejecutada: "Ejecutada (simulada)", verificada: "Verificada" };
const P_CLS = { pendiente: "warn", aprobada: "dup", rechazada: "bad", ejecutada: "dup", verificada: "ok" };

async function loadProposals(incidentId, closed) {
  const list = await api(`/api/incidents/${incidentId}/proposals`);
  const box = document.getElementById("p-list");
  box.replaceChildren();
  if (!list.length) box.append(el("p", "Sin propuestas todavía.", "muted small"));
  for (const p of list) {
    const card = el("div", "", "p-card");
    const head = el("div", "", "p-head");
    head.append(el("span", `#${p.id}`, "mono small"), el("span", P_LABEL[p.status], `tag ${P_CLS[p.status]}`),
                el("span", `riesgo ${p.risk}`, `tag ${p.risk === "alto" ? "bad" : p.risk === "medio" ? "warn" : "ok"}`),
                el("span", `propuesta por ${p.proposed_by}`, "muted small"));
    card.append(head, el("pre", p.command, "raw p-cmd"), el("div", p.justification || "", "small"));
    if (p.reviewed_by) card.append(el("div", `Revisó: ${p.reviewed_by} · ${fmtDate(p.reviewed_at)}`, "muted small"));
    if (p.result) card.append(el("div", p.result, "muted small"));
    if (!closed) card.append(proposalActions(p, incidentId));
    box.append(card);
  }
}

function proposalActions(p, incidentId) {
  const wrap = el("div", "", "inline-form");
  const call = async (path, body, msg) => {
    try {
      await api(`/api/proposals/${p.id}/${path}`, { method: "POST", headers: { "Content-Type": "application/json" },
                                                     body: JSON.stringify(body) });
      toast(msg); await loadProposals(incidentId, false);
    } catch (err) {
      document.getElementById("d-errors").replaceChildren(...err.message.split("\n").map(m => el("li", m)));
    }
  };
  if (p.status === "pendiente") {
    const input = el("input"); input.placeholder = "Motivo de la decisión (obligatorio)"; input.maxLength = 300;
    const ok = el("button", "Aprobar", "btn sm primary");
    const no = el("button", "Rechazar", "btn sm danger");
    ok.onclick = () => call("review", { decision: "aprobar", comment: input.value }, "Propuesta aprobada");
    no.onclick = () => call("review", { decision: "rechazar", comment: input.value }, "Propuesta rechazada");
    const label = el("label"); label.append("Revisión humana", input);
    wrap.append(label, ok, no);
  } else if (p.status === "aprobada") {
    const ex = el("button", "Ejecutar (simulado)", "btn sm primary");
    ex.onclick = () => call("execute", {}, "Acción ejecutada (simulación)");
    wrap.append(ex);
  } else if (p.status === "ejecutada") {
    const input = el("input"); input.placeholder = "Resultado verificado"; input.maxLength = 300;
    const v = el("button", "Verificar", "btn sm primary");
    v.onclick = () => call("verify", { result: input.value }, "Resultado verificado");
    const label = el("label"); label.append("Verificación", input);
    wrap.append(label, v);
  }
  return wrap;
}

document.getElementById("btn-suggest").onclick = async () => {
  try {
    const r = await api(`/api/incidents/${current.id}/suggest`, { method: "POST" });
    toast(r.created.length ? `${r.created.length} propuesta(s) nuevas del asistente` : "El asistente no tiene propuestas nuevas");
    await loadProposals(current.id, false);
  } catch (err) { toast(err.message, "err"); }
};
