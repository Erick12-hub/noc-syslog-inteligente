/*
 * Página de inventario: listar, crear, editar y eliminar equipos
 * usando la API /api/devices.
 */
const tbody = document.querySelector("#tbl-devices tbody");
const dlg = document.getElementById("dlg-device");
const frm = document.getElementById("frm-device");
const errorsBox = document.getElementById("frm-errors");
let devices = [];

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
    tr.append(src, el("td", fmtDate(d.updated_at), "small"));

    const actions = el("td", "", "row-actions");
    const bEdit = el("button", "Editar", "btn sm");
    bEdit.onclick = () => openForm(d);
    const bDel = el("button", "Eliminar", "btn sm danger");
    bDel.onclick = () => removeDevice(d);
    actions.append(bEdit, bDel);
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
    for (const f of ["name", "ip", "vendor", "status", "model", "version", "location"]) {
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
  for (const f of ["name", "ip", "vendor", "status", "model", "version", "location"]) {
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
  if (!confirm(`¿Eliminar ${d.name} (${d.ip})?\nSus eventos se conservan para la trazabilidad.`)) return;
  try {
    await api(`/api/devices/${d.id}`, { method: "DELETE" });
    toast(`${d.name} eliminado`);
    loadDevices();
  } catch (err) { toast(err.message, "err"); }
}

document.getElementById("btn-new").onclick = () => openForm();
document.getElementById("btn-cancel").onclick = () => dlg.close();
loadDevices().catch(err => toast(err.message, "err"));
