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
  cambio_autorizado: ["cambio autorizado (gestión de cambios)", "ok"],
  cuenta_servicio: ["regla: cuenta de servicio", "bad"],
  logs_deshabilitados: ["regla: logs deshabilitados", "bad"],
  puerto_invalido: ["puerto inválido", "warn"],
  interfaz_invalida: ["interfaz inválida", "warn"],
  fecha_futura: ["fecha futura (reloj/NTP)", "bad"],
  marca_inconsistente: ["marca inconsistente", "bad"],
  interfaz_desconocida: ["interfaz no registrada", "bad"],
};

/* Fase 7: texto de interfaz y puertos.  ej. "wan1 · 51520 → 3389" */
function netText(e) {
  const parts = [];
  if (e.interface) parts.push(e.interface);
  if (e.src_port || e.dst_port) parts.push(`${e.src_port ?? "?"} → ${e.dst_port ?? "?"}`);
  return parts.join(" · ") || "—";
}

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

/* ---------------------------------------------------------------------------
 * Fase 7: filtro de fecha hasta HOY (hora de Colombia).
 * La fecha de hoy la entrega el SERVIDOR (/api/events/today): si el reloj o la
 * zona horaria del PC del operador están mal, el límite sigue siendo correcto.
 * Esta validación es solo una ayuda; la que manda es la del servidor (400).
 * ------------------------------------------------------------------------- */
const fDesde = document.getElementById("f-desde");
const fHasta = document.getElementById("f-hasta");
const filterWarning = document.getElementById("filter-warning");
let today = null;

async function setupDateLimits() {
  today = (await api("/api/events/today")).today;   // "AAAA-MM-DD"
  fDesde.max = today;
  fHasta.max = today;
}

/** Devuelve la lista de problemas del rango de fechas (vacía si está bien). */
function dateProblems() {
  const problems = [];
  for (const [label, input] of [["Desde", fDesde], ["Hasta", fHasta]]) {
    if (input.value && today && input.value > today)   // AAAA-MM-DD se compara bien como texto
      problems.push(`${label} (${input.value}) es posterior a hoy (${today}). Solo se consultan hoy e histórico.`);
  }
  if (fDesde.value && fHasta.value && fDesde.value > fHasta.value)
    problems.push("'Desde' no puede ser posterior a 'Hasta'.");
  return problems;
}

function showFilterWarning(problems) {
  filterWarning.hidden = problems.length === 0;
  filterWarning.textContent = problems.length ? `⚠ ${problems.join(" ")}` : "";
}

// 'Hasta' no puede ser anterior a 'Desde': se ajusta el mínimo permitido
fDesde.addEventListener("change", () => { fHasta.min = fDesde.value || ""; showFilterWarning(dateProblems()); });
fHasta.addEventListener("change", () => showFilterWarning(dateProblems()));

/* Fase 7.4: paginación. Se piden 100 eventos por página en lugar de 200 de golpe;
 * el total y el número de páginas llegan en encabezados HTTP (X-Total-Count...). */
const PER_PAGE = 100;
let currentPage = 1;

async function loadEvents(page = 1) {
  // Solo se envían los filtros con valor
  const params = new URLSearchParams();
  for (const [k, v] of new FormData(frmFilters)) if (v) params.append(k, v);
  params.append("limit", PER_PAGE);
  params.append("page", page);
  // fetch directo (no api()) para poder leer los encabezados de paginación
  const res = await fetch(`/api/events?${params}`);
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(((body && body.errors) || [`Error HTTP ${res.status}`]).join("\n"));
  const events = body;
  const total = Number(res.headers.get("X-Total-Count") || events.length);
  const pages = Number(res.headers.get("X-Total-Pages") || 1);
  currentPage = page;

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
              el("td", e.mnemonic || "—", "mono small"), el("td", netText(e), "mono small"), msg, el("td", e.origin, "small"),
              flagChips(e.flags));
    tr.onclick = () => showEvent(e.id);
    evBody.append(tr);
  }
  const first = total ? (page - 1) * PER_PAGE + 1 : 0;
  document.getElementById("events-count").textContent =
    `Eventos ${first}–${first + events.length - (total ? 1 : 0)} de ${total} · página ${page} de ${pages}` +
    " · clic en una fila para ver el detalle";
  document.getElementById("btn-prev").disabled = page <= 1;
  document.getElementById("btn-next").disabled = page >= pages;
}

document.getElementById("btn-prev").onclick = () => loadEvents(currentPage - 1).catch(e => toast(e.message, "err"));
document.getElementById("btn-next").onclick = () => loadEvents(currentPage + 1).catch(e => toast(e.message, "err"));

async function showEvent(id) {
  const e = await api(`/api/events/${id}`);
  document.getElementById("ev-id").textContent = `#${e.id}`;
  const dl = document.getElementById("ev-detail");
  dl.replaceChildren();
  const rows = [
    ["Recibido (local)", fmtDate(e.received_at)], ["Fecha del mensaje", e.event_time || "—"],
    ["Fecha del mensaje (local)", e.event_time_utc ? fmtDate(e.event_time_utc) : "—"],
    ["IP de origen", e.source_ip], ["Equipo", e.device_name || "no registrado"],
    ["Fuente autorizada", e.authorized_source ? "Sí" : "NO"], ["Marca", e.vendor],
    ["Facility", `${e.facility} (${FACILITIES[e.facility]})`], ["Severidad", `${e.severity} (${e.severity_name})`],
    ["Código fabricante", e.mnemonic || "—"], ["Aplicación", e.app_name || "—"],
    ["Interfaz", e.interface || "—"], ["Puerto de origen", e.src_port ?? "—"],
    ["Puerto de destino", e.dst_port ?? "—"],
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
  const importErrors = document.getElementById("import-errors");
  importErrors.replaceChildren();
  try {
    const s = await api("/api/events/import", { method: "POST", body: new FormData(ev.target) });
    toast(`Importación: ${s.nuevas} nuevos, ${s.duplicadas} duplicados, ${s.ignoradas} ignorados`);
    ev.target.reset();
    loadEvents();
  } catch (err) {
    // Fase 7.3: el motivo queda visible (el toast desaparece a los 4 s)
    importErrors.replaceChildren(...err.message.split("\n").map(m => el("li", m)));
    toast("Importación rechazada", "err");
  }
});

frmFilters.addEventListener("submit", (ev) => {
  ev.preventDefault();
  const problems = dateProblems();
  showFilterWarning(problems);
  if (problems.length) return;                 // no se consulta con fechas inválidas
  // Si el servidor rechaza algo (400), su mensaje también se muestra en el aviso
  loadEvents().catch(e => { showFilterWarning([e.message]); toast(e.message, "err"); });
});
// novalidate: el aviso propio reemplaza la burbuja del navegador, que desaparece
// sola y no explica la regla. El servidor valida igual (respuesta 400).
frmFilters.noValidate = true;
document.getElementById("btn-clear").onclick = () => setTimeout(() => {
  fHasta.min = ""; showFilterWarning([]); loadEvents();
}, 0);
document.getElementById("btn-refresh").onclick = () => loadEvents(currentPage);
document.getElementById("btn-close-ev").onclick = () => document.getElementById("dlg-event").close();

Promise.all([loadDeviceOptions(), setupDateLimits()]).then(() => loadEvents()).catch(err => toast(err.message, "err"));
