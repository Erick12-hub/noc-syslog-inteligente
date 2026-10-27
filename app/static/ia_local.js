/* Asistente de IA local: estado, borradores y datos enviados al modelo.
 * Todo el texto (incluido el del modelo) se inserta con textContent: nunca se interpreta como HTML. */
const statusBox = document.getElementById("ia-status");
const jobBox = document.getElementById("job-status");
const frmDraft = document.getElementById("frm-draft");
let polling = null;

function fmtSize(n) { return n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`; }

async function loadStatus() {
  const s = await api("/api/ia-local/estado");
  statusBox.replaceChildren();
  const line = el("div");
  line.append(el("span", s.ok ? "Listo" : "No disponible", `tag ${s.ok ? "ok" : "bad"}`), document.createTextNode(" "),
              el("span", `Ollama en ${s.url} · modelo ${s.model}`, "mono small"));
  statusBox.append(line);
  if (s.models && s.models.length) statusBox.append(el("div", `Modelos descargados: ${s.models.join(", ")}`, "muted small"));
  if (s.error) statusBox.append(el("div", s.error, "small warn-text"));
  showJob(s.job);
  return s;
}

function showJob(job) {
  if (!jobBox || !job) return;
  const btn = document.getElementById("btn-generate");
  jobBox.replaceChildren();
  if (job.running) {
    jobBox.append(el("span", "Generando…", "tag warn"),
                  document.createTextNode(` ${job.kind} pedido por ${job.user} (${fmtDate(job.started)}). No cierre el NOC.`));
    if (btn) btn.disabled = true;
    if (!polling) polling = setInterval(() => loadStatus().then(st => {
      if (!st.job.running) { clearInterval(polling); polling = null; loadDrafts(); if (st.job.result) openDraft(st.job.result); }
    }).catch(() => {}), 5000);
  } else {
    if (btn) btn.disabled = false;
    if (job.error) jobBox.append(el("span", "Error", "tag bad"), document.createTextNode(" " + job.error));
    else if (job.result) jobBox.append(el("span", "Listo", "tag ok"), document.createTextNode(" " + job.result));
  }
}

async function loadDrafts() {
  const r = await api("/api/ia-local/borradores");
  const tb = document.getElementById("tbl-drafts");
  tb.replaceChildren();
  for (const d of r.drafts) {
    const tr = el("tr");
    const btn = el("button", "Ver", "btn sm");
    btn.onclick = () => openDraft(d.name);
    const act = el("td"); act.append(btn);
    tr.append(el("td", d.name, "mono small"), el("td", d.kind === "bitacora" ? "Bitácora" : "Informe"),
              el("td", fmtDate(d.modified), "small"), el("td", fmtSize(d.size), "small"), act);
    tb.append(tr);
  }
  document.getElementById("drafts-count").textContent =
    r.drafts.length ? `${r.drafts.length} borrador(es) en data/borradores_ia (fuera de GitHub)` : "Aún no hay borradores.";
}

async function openDraft(name) {
  const r = await api(`/api/ia-local/borradores/${encodeURIComponent(name)}`);
  document.getElementById("viewer").hidden = false;
  document.getElementById("viewer-title").textContent = r.name;
  document.getElementById("viewer-text").textContent = r.text;
  document.getElementById("viewer-sha").textContent = `SHA-256: ${r.sha256}`;
  document.getElementById("viewer").scrollIntoView({ behavior: "smooth" });
}

if (frmDraft) frmDraft.addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(frmDraft);
  try {
    const r = await api("/api/ia-local/borradores", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tipo: f.get("tipo"), dias: f.get("dias") }),
    });
    toast("Generando el borrador con la IA local…");
    showJob(r.job);
    if (!r.job.running) { loadDrafts(); if (r.job.result) openDraft(r.job.result); }
  } catch (err) { toast(err.message, "err"); }
});

document.getElementById("frm-context").addEventListener("submit", async (e) => {
  e.preventDefault();
  const dias = new FormData(e.target).get("dias");
  try {
    const ctx = await api(`/api/ia-local/contexto?dias=${encodeURIComponent(dias)}`);
    const pre = document.getElementById("context-text");
    pre.hidden = false;
    pre.textContent = JSON.stringify(ctx, null, 2);
  } catch (err) { toast(err.message, "err"); }
});

document.getElementById("btn-refresh").onclick = () => { loadStatus(); loadDrafts(); };
loadStatus().catch(err => toast(err.message, "err"));
loadDrafts().catch(err => toast(err.message, "err"));
