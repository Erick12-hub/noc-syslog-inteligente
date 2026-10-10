/*
 * Página de eventos: tabla con filtros, detalle del evento e importación
 * de archivos. Consume /api/events y /api/devices.
 */
const evBody = document.querySelector("#tbl-events tbody");
const frmFilters = document.getElementById("frm-filters");
const FACILITIES = ["kern","user","mail","daemon","auth","syslog","lpr","news","uucp","cron","authpriv","ftp",
  "ntp","security","console","clock","local0","local1","local2","local3","local4","local5","local6","local7"];
const FLAG_LABELS = {
  fuente_no_autorizada: ["fuente no autorizada", "bad"],
  equipo_desconocido: ["equipo desconocido", "warn"],
  posible_prompt_injection: ["posible prompt injection", "bad"],
  severidad_inconsistente: ["severidad inconsistente", "warn"],
  sin_pri: ["sin PRI", "warn"],
  severidad_asumida: ["severidad asumida", "warn"],
  mensaje_recortado: ["recortado", "warn"],
  login_fallido: ["login fallido", "warn"],
  cambio_config: ["cambio de configuración", "dup"],
  fuerza_bruta: ["regla: fuerza bruta", "bad"],
  cambio_fuera_de_horario: ["regla: fuera de horario", "bad"],
  cuenta_servicio: ["regla: cuenta de servicio", "bad"],
  logs_deshabilitados: ["regla: logs deshabilitados", "bad"],
};

async function loadDeviceOptions() {
  const devices = await api("/api/devices");
  for (const sel of document.querySelectorAll('select[name="device_id"]')) {
    for (const d of devices) {
      const o = el("option", `${d.name} (${d.ip})`);
      o.value = d.id;
      sel.append(o);
    }
  }
}

function flagChips(flags) {
  const td = el("td");
  for (const f of (flags || "").split(",").filter(Boolean)) {
    const [label, kind] = FLAG_LABELS[f] || [f, "warn"];
    td.append(el("span", label, `tag ${kind}`), " ");
  }
  return td;
}

async function loadEvents() {
  // Solo se envían los filtros con valor
  const params = new URLSearchParams();
  for (const [k, v] of new FormData(frmFilters)) if (v) params.append(k, v);
  params.append("limit", "200");
  const events = await api(`/api/events?${params}`);

  evBody.replaceChildren();
  for (const e of events) {
    const tr = document.createElement("tr");
    if (e.severity <= 3) tr.className = "row-critical";
    const sev = el("td"); sev.append(severityBadge(e.severity));
    const dev = el("td");
    dev.append(el("span", e.device_name || e.source_ip));
    if (e.is_simulated) dev.append(" ", el("span", "SIM", "tag sim"));
    const msg = el("td", e.message, "msg");
    if (e.dup_count > 1) msg.prepend(el("span", `x${e.dup_count}`, "tag dup"), " ");
    tr.append(el("td", e.id, "mono small"), el("td", fmtDate(e.received_at), "small"), sev, dev,
              el("td", e.vendor), el("td", FACILITIES[e.facility] ?? e.facility, "small"),
              el("td", e.mnemonic || "—", "mono small"), msg, el("td", e.origin, "small"),
              flagChips(e.flags));
    tr.onclick = () => showEvent(e.id);
    evBody.append(tr);
  }
  document.getElementById("events-count").textContent =
    `${events.length} eventos mostrados (máx. 200) · clic en una fila para ver el detalle`;
}

async function showEvent(id) {
  const e = await api(`/api/events/${id}`);
  document.getElementById("ev-id").textContent = `#${e.id}`;
  const dl = document.getElementById("ev-detail");
  dl.replaceChildren();
  const rows = [
    ["Recibido (local)", fmtDate(e.received_at)], ["Fecha del mensaje", e.event_time || "—"],
    ["IP de origen", e.source_ip], ["Equipo", e.device_name || "no registrado"],
    ["Fuente autorizada", e.authorized_source ? "Sí" : "NO"], ["Marca", e.vendor],
    ["Facility", `${e.facility} (${FACILITIES[e.facility]})`], ["Severidad", `${e.severity} (${e.severity_name})`],
    ["Código fabricante", e.mnemonic || "—"], ["Aplicación", e.app_name || "—"],
    ["Repeticiones", e.dup_count], ["Origen", e.origin], ["Marcas", e.flags || "ninguna"],
    ["Simulado", e.is_simulated ? "Sí" : "No"],
  ];
  for (const [k, v] of rows) dl.append(el("dt", k), el("dd", v));
  document.getElementById("ev-raw").textContent = e.raw;   // texto, nunca HTML
  document.getElementById("ev-errors").replaceChildren();
  document.getElementById("btn-ev-incident").onclick = () => incidentFromEvent(e.id);
  document.getElementById("dlg-event").showModal();
}

/* Crea un incidente a partir del evento. Si ya existe uno abierto, ofrece abrirlo. */
async function incidentFromEvent(eventId) {
  const res = await fetch("/api/incidents", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_id: eventId }),
  });
  const body = await res.json().catch(() => ({}));
  if (res.ok || res.status === 409) {
    location.href = `/incidentes#${res.ok ? body.id : body.incident_id}`;
  } else {
    document.getElementById("ev-errors").replaceChildren(...(body.errors || ["Error"]).map(m => el("li", m)));
  }
}

document.getElementById("frm-import").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    const s = await api("/api/events/import", { method: "POST", body: new FormData(ev.target) });
    toast(`Importación: ${s.nuevas} nuevos, ${s.duplicadas} duplicados, ${s.ignoradas} ignorados`);
    ev.target.reset();
    loadEvents();
  } catch (err) { toast(err.message, "err"); }
});

frmFilters.addEventListener("submit", (ev) => { ev.preventDefault(); loadEvents().catch(e => toast(e.message, "err")); });
document.getElementById("btn-clear").onclick = () => setTimeout(loadEvents, 0);
document.getElementById("btn-refresh").onclick = () => loadEvents();
document.getElementById("btn-close-ev").onclick = () => document.getElementById("dlg-event").close();

loadDeviceOptions().then(loadEvents).catch(err => toast(err.message, "err"));
