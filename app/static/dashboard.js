/*
 * Dashboard: consulta /api/dashboard cada 15 s y dibuja indicadores,
 * gráficas (barras HTML, sin librerías) y tablas.
 * Todo el texto se inserta con textContent (ver common.js).
 */
const REFRESH_MS = 15000;
const STATUS_ORDER = ["activo", "alerta", "caido", "mantenimiento", "desconocido"];
const STATUS_LABEL = { activo: "Activo", alerta: "Alerta", caido: "Caído", mantenimiento: "Mantenimiento", desconocido: "Desconocido" };
const INC_LABEL = { abierto: "Abierto", asignado: "Asignado", en_progreso: "En progreso", cerrado: "Cerrado" };

function setText(id, text) { document.getElementById(id).textContent = text; }

function renderKpis(d) {
  setText("k-devices", d.devices.total);
  setText("k-devices-sub", `${d.devices.by_status.activo || 0} activos · ${d.devices.authorized} fuentes autorizadas`);
  setText("k-events", d.events_24h.eventos);
  setText("k-events-sub", `${d.events_24h.mensajes} mensajes recibidos (con repeticiones)`);
  setText("k-critical", d.events_24h.criticos);
  setText("k-incidents", d.incidents.open);
  const bs = d.incidents.by_status;
  setText("k-incidents-sub", `${bs.abierto || 0} sin asignar · ${bs.cerrado || 0} cerrados`);
  setText("k-security", d.events_24h.no_autorizados + d.events_24h.inyeccion);
  setText("k-security-sub", `${d.events_24h.no_autorizados} fuente no autorizada · ${d.events_24h.inyeccion} posible inyección`);
}

function renderDeviceStatus(d) {
  const ul = document.getElementById("device-status");
  ul.replaceChildren();
  for (const s of STATUS_ORDER) {
    const n = d.devices.by_status[s] || 0;
    const li = el("li");
    li.append(el("span", STATUS_LABEL[s], `status st-${s}`), el("strong", n, "mono"));
    ul.append(li);
  }
}

/* Barras horizontales: una por severidad. La longitud es proporcional al máximo. */
function renderSeverity(d) {
  const box = document.getElementById("sev-bars");
  box.replaceChildren();
  const max = Math.max(1, ...d.by_severity);
  d.by_severity.forEach((n, sev) => {
    const row = el("div", "", "sev-row");
    row.title = `${sev} ${SEVERITY[sev]}: ${n} eventos`;
    const track = el("div", "", "sev-track");
    const bar = el("div", "", `sev-fill sevbg-${sev}`);
    bar.style.width = `${(n / max) * 100}%`;
    track.append(bar);
    row.append(el("span", `${sev} ${SEVERITY[sev]}`, "sev-name"), track, el("span", n, "sev-count mono"));
    box.append(row);
  });
}

/* Columnas por hora: total (gris) y críticos superpuestos (rojo), misma escala. */
function renderHours(d) {
  const chart = document.getElementById("hour-chart");
  const axis = document.getElementById("hour-axis");
  chart.replaceChildren(); axis.replaceChildren();
  const max = Math.max(1, ...d.by_hour.map(h => h.total));
  d.by_hour.forEach((h, i) => {
    const date = new Date(h.hour);
    const label = date.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
    const col = el("div", "", "hour-col");
    col.title = `${label}: ${h.total} eventos, ${h.critical} críticos`;
    const total = el("div", "", "hour-bar total");
    total.style.height = `${(h.total / max) * 100}%`;
    const crit = el("div", "", "hour-bar crit");
    crit.style.height = `${(h.critical / max) * 100}%`;
    col.append(total, crit);
    chart.append(col);
    // Etiqueta cada 3 horas para que no se amontonen
    axis.append(el("span", i % 3 === 0 || i === 23 ? label : ""));
  });
  chart.setAttribute("aria-label", `Eventos por hora; máximo ${max} en una hora`);
}

function renderIncidents(d) {
  const tb = document.getElementById("tbl-incidents");
  tb.replaceChildren();
  if (!d.open_incidents.length) {
    const tr = el("tr"); const td = el("td", "No hay incidentes abiertos", "muted");
    td.colSpan = 5; tr.append(td); tb.append(tr); return;
  }
  for (const i of d.open_incidents) {
    const tr = el("tr", "", "clickable");
    const sev = el("td"); sev.append(severityBadge(i.severity));
    const st = el("td"); st.append(el("span", INC_LABEL[i.status], `inc-status inc-${i.status}`));
    const title = el("td"); title.append(el("div", i.title));
    if (i.assigned_to) title.append(el("div", `Responsable: ${i.assigned_to}`, "muted small"));
    tr.append(el("td", i.id, "mono small"), sev, title, st, el("td", i.event_count, "mono"));
    tr.onclick = () => (location.href = `/incidentes#${i.id}`);
    tb.append(tr);
  }
}

function renderCritical(d) {
  const tb = document.getElementById("tbl-critical");
  tb.replaceChildren();
  if (!d.recent_critical.length) {
    const tr = el("tr"); const td = el("td", "Sin eventos críticos", "muted");
    td.colSpan = 4; tr.append(td); tb.append(tr); return;
  }
  for (const e of d.recent_critical) {
    const tr = el("tr");
    const sev = el("td"); sev.append(severityBadge(e.severity));
    const msg = el("td", e.message, "msg");
    if (e.dup_count > 1) msg.prepend(el("span", `x${e.dup_count}`, "tag dup"), " ");
    if ((e.flags || "").includes("fuente_no_autorizada")) msg.append(" ", el("span", "no autorizada", "tag bad"));
    tr.append(el("td", fmtDate(e.received_at), "small"), sev, el("td", e.device_name || e.source_ip), msg);
    tb.append(tr);
  }
}

async function refresh() {
  try {
    const d = await api("/api/dashboard");
    renderKpis(d); renderDeviceStatus(d); renderSeverity(d); renderHours(d);
    renderIncidents(d); renderCritical(d);
    setText("updated", `actualizado ${new Date().toLocaleTimeString("es-CO")}`);
  } catch (err) {
    setText("updated", "sin conexión con el servidor");
    toast(err.message, "err");
  }
}

document.getElementById("btn-refresh").onclick = refresh;
refresh();
setInterval(refresh, REFRESH_MS);
