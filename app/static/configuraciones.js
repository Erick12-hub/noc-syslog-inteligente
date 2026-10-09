/*
 * Generador de configuraciones: pide /api/config/generate y muestra el texto.
 * Al elegir un equipo se completan la marca y una interfaz típica.
 */
const DEFAULT_IFACE = { Cisco: "GigabitEthernet0/0/0", Fortinet: "wan1", Huawei: "GigabitEthernet0/0/0" };
const out = document.getElementById("cfg-out");
const btnCopy = document.getElementById("btn-copy");
let devices = [];

async function loadDevices() {
  devices = await api("/api/devices");
  const sel = document.getElementById("cfg-device");
  for (const d of devices.filter(d => d.vendor !== "Otro")) {
    const o = el("option", `${d.name} (${d.vendor}, ${d.ip})`); o.value = d.id; sel.append(o);
  }
}

document.getElementById("cfg-device").addEventListener("change", (e) => {
  const d = devices.find(x => String(x.id) === e.target.value);
  if (d) {
    document.getElementById("cfg-vendor").value = d.vendor;
    document.getElementById("cfg-source").value = DEFAULT_IFACE[d.vendor];
  }
});
document.getElementById("cfg-vendor").addEventListener("change", (e) => {
  document.getElementById("cfg-source").value = DEFAULT_IFACE[e.target.value];
});

document.getElementById("frm-config").addEventListener("submit", async (e) => {
  e.preventDefault();
  const params = new URLSearchParams();
  for (const [k, v] of new FormData(e.target)) if (v) params.append(k, v);
  const errBox = document.getElementById("cfg-errors");
  try {
    const r = await api(`/api/config/generate?${params}`);
    errBox.replaceChildren();
    out.textContent = r.config;          // texto plano, nunca HTML
    document.getElementById("cfg-title").textContent = `Configuración ${r.vendor}`;
    btnCopy.disabled = false;
  } catch (err) {
    errBox.replaceChildren(...err.message.split("\n").map(m => el("li", m)));
  }
});

btnCopy.onclick = async () => {
  try { await navigator.clipboard.writeText(out.textContent); toast("Configuración copiada"); }
  catch (_) {   // si el navegador no permite copiar, se selecciona el texto
    const range = document.createRange(); range.selectNodeContents(out);
    const s = getSelection(); s.removeAllRanges(); s.addRange(range);
    toast("Texto seleccionado: presione Ctrl+C");
  }
};

loadDevices().catch(err => toast(err.message, "err"));
