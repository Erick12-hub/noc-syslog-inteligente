/*
 * Consola simulada: envía cada comando a /api/console y muestra la salida o
 * el motivo del bloqueo. El historial vive solo en la página.
 */
const term = document.getElementById("terminal");
const devSel = document.getElementById("con-device");
let devices = [];

function prompt() {
  const d = devices.find(x => String(x.id) === devSel.value);
  if (!d) return "#";
  if (d.vendor === "Huawei") return `<${d.name}>`;
  if (d.vendor === "Fortinet") return `${d.name} #`;
  return `${d.name}#`;
}

function line(text, cls = "") { term.append(el("div", text, `tl ${cls}`)); term.scrollTop = term.scrollHeight; }

async function loadAllowed() {
  const d = devices.find(x => String(x.id) === devSel.value);
  document.getElementById("prompt").textContent = prompt();
  const ul = document.getElementById("allow-list");
  ul.replaceChildren();
  const r = await api(`/api/console/allowed?vendor=${encodeURIComponent(d.vendor)}`);
  for (const c of r.allowed) {
    const li = el("li"); const code = el("code", c.command, "clickable");
    code.title = "Clic para escribirlo"; code.onclick = () => { document.getElementById("cmd").value = c.command; document.getElementById("cmd").focus(); };
    li.append(code, el("span", ` ${c.description}`, "muted small")); ul.append(li);
  }
  if (!r.allowed.length) ul.append(el("li", "Este equipo no tiene comandos permitidos.", "muted"));
  line(`--- Sesión SIMULADA con ${d.name} (${d.vendor}, ${d.ip}) ---`, "tl-info");
}

document.getElementById("frm-cmd").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("cmd");
  const command = input.value;
  if (!command.trim()) return;
  input.value = "";
  const actor = document.getElementById("con-actor").value;
  line(`${prompt()} ${command}${actor === "asistente_ia" ? "   [orden del asistente de IA]" : ""}`, "tl-cmd");
  const res = await fetch("/api/console", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_id: devSel.value, command, actor }),
  });
  const body = await res.json().catch(() => ({}));
  if (body.allowed) {
    for (const l of body.output.split("\n")) line(l);   // texto, nunca HTML
  } else {
    line(`% BLOQUEADO: ${body.reason || (body.errors || ["error"]).join(" ")}`, "tl-block");
    line("% El intento quedó registrado en la auditoría.", "tl-info");
  }
});

devSel.addEventListener("change", () => loadAllowed().catch(err => toast(err.message, "err")));

(async () => {
  devices = (await api("/api/devices")).filter(d => d.vendor !== "Otro");
  for (const d of devices) { const o = el("option", `${d.name} (${d.vendor})`); o.value = d.id; devSel.append(o); }
  await loadAllowed();
})().catch(err => toast(err.message, "err"));
