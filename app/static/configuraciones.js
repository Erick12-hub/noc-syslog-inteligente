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
  // Fase 9.2: solo equipos Cisco para la configuración base
  const bs = document.getElementById("bs-device");
  for (const d of devices.filter(d => d.vendor === "Cisco")) {
    const o = el("option", `${d.name} (${d.ip})`); o.value = d.id; bs.append(o);
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

/* ---------------------------------------------------------------------------
 * Fase 9.2: configuración base desde cero (bloques para PuTTY)
 * ------------------------------------------------------------------------- */
// Direccionamiento SUGERIDO para pruebas (plan del laboratorio, 192.168.100.0/24).
// Todas las casillas se pueden cambiar a mano con los datos del equipo real.
const LAB = {
  router: { hostname: "LAB-RTR01", iface: "GigabitEthernet0/0/0", ip: "192.168.100.1", gw: "" },
  switch: { hostname: "LAB-SW01", iface: "Vlan1", ip: "192.168.100.2", gw: "192.168.100.1" },
};
const LAB_NOC = { ip: "192.168.100.10", prefix: "24" };
const SYSLOG_PORT = document.getElementById("bs-port").value;
const KIND = { manual: ["escribir a mano", "warn"], pegar: ["pegar en PuTTY", "ok"],
               verificar: ["verificar", "dup"] };

function setRole(role) {            // llena el SUGERIDO del rol (se puede editar después)
  document.getElementById("bs-role").value = role;
  document.getElementById("bs-hostname").value = LAB[role].hostname;
  document.getElementById("bs-if").value = LAB[role].iface;
  document.getElementById("bs-ip").value = LAB[role].ip;
  document.getElementById("bs-gw").value = LAB[role].gw;
}
document.getElementById("btn-bs-suggest").onclick = () => {
  setRole(document.getElementById("bs-role").value);
  document.getElementById("bs-noc").value = LAB_NOC.ip;
  document.getElementById("bs-prefix").value = LAB_NOC.prefix;
  document.getElementById("bs-port").value = SYSLOG_PORT;
  document.getElementById("bs-device").value = "";
  toast("Direccionamiento sugerido del laboratorio");
};
document.getElementById("bs-role").addEventListener("change", (e) => setRole(e.target.value));
document.getElementById("bs-device").addEventListener("change", (e) => {
  const d = devices.find(x => String(x.id) === e.target.value);
  if (!d) return;
  setRole(d.platform === "cisco_ios" ? "switch" : "router");
  document.getElementById("bs-hostname").value = d.name;
  document.getElementById("bs-ip").value = d.ip;
});

async function copyText(text, node) {
  try { await navigator.clipboard.writeText(text); toast("Bloque copiado"); }
  catch (_) {
    const range = document.createRange(); range.selectNodeContents(node);
    const s = getSelection(); s.removeAllRanges(); s.addRange(range);
    toast("Texto seleccionado: presione Ctrl+C");
  }
}

document.getElementById("frm-base").addEventListener("submit", async (e) => {
  e.preventDefault();
  const params = new URLSearchParams();
  for (const [k, v] of new FormData(e.target)) if (v) params.append(k, v);
  const errBox = document.getElementById("bs-errors");
  const box = document.getElementById("bs-blocks");
  try {
    const r = await api(`/api/config/baseline?${params}`);
    errBox.replaceChildren();
    box.replaceChildren();
    for (const b of r.blocks) {
      const card = el("section", "", `card block-${b.kind}`);
      const head = el("div", "", "chart-head");
      const title = el("h2", b.title);
      const [label, cls] = KIND[b.kind];
      title.append(" ", el("span", label, `tag ${cls}`));
      if (b.chunks) {
        // Fase 9.5 (hallazgo del laboratorio): un botón por trozo; pegar todo junto pierde líneas
        head.append(title);
        card.append(head, el("p", "Pegue un trozo, espere el prompt (#) y siga con el siguiente.", "muted small"));
        const grid = el("div", "", "chunk-grid");
        for (const c of b.chunks) {
          const item = el("div", "", "chunk");
          const pre = el("pre", c.text, "raw config-out");  // texto plano, nunca HTML
          const btn = el("button", "Copiar", "btn sm");
          btn.onclick = () => { copyText(c.text, pre); item.classList.add("copied"); };
          const ch = el("div", "", "chunk-head");
          ch.append(el("strong", c.title), btn);
          item.append(ch, pre);
          grid.append(item);
        }
        card.append(grid);
      } else {
        const pre = el("pre", b.text, "raw config-out");   // texto plano, nunca HTML
        const btn = el("button", "Copiar", "btn sm");
        btn.onclick = () => copyText(b.text, pre);
        head.append(title, btn);
        card.append(head, pre);
      }
      box.append(card);
    }
  } catch (err) {
    box.replaceChildren();
    errBox.replaceChildren(...err.message.split("\n").map(m => el("li", m)));
  }
});

loadDevices().catch(err => toast(err.message, "err"));
