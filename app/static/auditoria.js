/* Auditoría: lista /api/audit con filtros. */
const frm = document.getElementById("frm-audit");
const RESULT_CLS = { ok: "ok", alerta: "warn", bloqueado: "bad", error: "bad" };
let actorsLoaded = false;

async function load() {
  const params = new URLSearchParams();
  for (const [k, v] of new FormData(frm)) if (v) params.append(k, v);
  const r = await api(`/api/audit?${params}`);
  if (!actorsLoaded) {
    const sel = document.getElementById("au-actor");
    for (const a of r.actors) { const o = el("option", a); o.value = a; sel.append(o); }
    actorsLoaded = true;
  }
  const tb = document.getElementById("tbl-audit");
  tb.replaceChildren();
  for (const a of r.rows) {
    const tr = el("tr");
    const actor = el("td"); actor.append(el("span", a.actor, a.actor === "asistente_ia" ? "tag dup" : ""));
    const res = el("td"); res.append(el("span", a.result, `tag ${RESULT_CLS[a.result] || ""}`));
    tr.append(el("td", a.id, "mono small"), el("td", fmtDate(a.ts), "small"), actor,
              el("td", a.action, "mono small"), el("td", a.detail || "—", "msg small"), res);
    tb.append(tr);
  }
  document.getElementById("au-count").textContent = `${r.rows.length} registros (máx. 200)`;
}

frm.addEventListener("submit", (e) => { e.preventDefault(); load().catch(err => toast(err.message, "err")); });
document.getElementById("btn-clear").onclick = () => setTimeout(load, 0);
document.getElementById("btn-refresh").onclick = () => load();
load().catch(err => toast(err.message, "err"));
