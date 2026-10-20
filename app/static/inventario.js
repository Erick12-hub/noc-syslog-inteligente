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
    tr.append(src, ifc, el("td", fmtDate(d.updated_at), "small"));

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
  if (!confirm(`¿Eliminar ${d.name} (${d.ip})?\nSus eventos se conservan para la trazabilidad;` +
               ` sus ${d.interface_count ?? 0} interfaces se eliminan.`)) return;
  try {
    await api(`/api/devices/${d.id}`, { method: "DELETE" });
    toast(`${d.name} eliminado`);
    loadDevices();
  } catch (err) { toast(err.message, "err"); }
}

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
    tr.append(el("td", i.name, "mono"), el("td", i.description || "—"), st,
              el("td", fmtDate(i.updated_at), "small"));
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
    td.colSpan = 5; tr.append(td); ifBody.append(tr);
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

document.getElementById("btn-if-reset").onclick = resetIfaceForm;
document.getElementById("btn-if-close").onclick = () => dlgIf.close();

const btnNew = document.getElementById("btn-new");   // no existe para el auditor
if (btnNew) btnNew.onclick = () => openForm();
document.getElementById("btn-cancel").onclick = () => dlg.close();
loadDevices().catch(err => toast(err.message, "err"));
