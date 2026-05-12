const $ = (s) => document.querySelector(s);
let _targets = [];

async function api(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

async function loadHealth() {
  try {
    const h = await api("/api/health");
    $("#repos-pill").textContent = h.repos_dir;
    $("#repos-pill").className = "pill ok";
  } catch {
    $("#repos-pill").textContent = "offline";
    $("#repos-pill").className = "pill err";
  }
}

async function loadTargets() {
  const data = await api("/api/targets");
  _targets = data.targets || [];
  const sel = $("#project-select");
  sel.innerHTML = "";
  _targets.forEach((t) => {
    const o = document.createElement("option");
    o.value = t.name;
    o.textContent = `${t.name} [${t.language}${t.has_git ? "" : ", no-git"}]`;
    sel.appendChild(o);
  });
  renderTargets();
}

function renderTargets() {
  const box = $("#targets-list");
  const f = ($("#targets-filter").value || "").toLowerCase();
  box.innerHTML = "";
  _targets.filter((t) => !f || t.name.toLowerCase().includes(f)).forEach((t) => {
    const l = document.createElement("label");
    l.className = t.enabled ? "" : "disabled";
    l.innerHTML = `<input type="checkbox" data-name="${escapeAttr(t.name)}" ${t.enabled ? "checked" : ""}>
      <span>${escapeHtml(t.name)}</span>
      <span class="lang">${t.language}${t.has_git ? "" : " · no-git"}</span>`;
    box.appendChild(l);
  });
  $("#targets-summary").textContent = `${_targets.filter((t) => t.enabled).length} / ${_targets.length} enabled`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
}
function escapeAttr(s) { return escapeHtml(s); }

async function loadReports() {
  const { projects } = await api("/api/reports");
  const box = $("#reports-tree");
  box.innerHTML = "";
  const entries = Object.entries(projects);
  if (!entries.length) { box.innerHTML = `<p class="muted">No reports yet. Run an audit.</p>`; return; }
  entries.forEach(([proj, files]) => {
    const d = document.createElement("div");
    d.className = "report-group";
    d.innerHTML = `<h3>${escapeHtml(proj)}</h3>` + files
      .map((f) => `<a href="#" data-project="${escapeAttr(proj)}" data-file="${escapeAttr(f)}">${escapeHtml(f)}</a>`)
      .join("");
    box.appendChild(d);
  });
}

async function openReport(project, file) {
  const m = $("#report-modal");
  m.classList.remove("hidden");
  $("#modal-title").textContent = `${project} / ${file}`;
  const c = $("#modal-content");
  c.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    const r = await fetch(`/api/report?project=${encodeURIComponent(project)}&file=${encodeURIComponent(file)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const md = await r.text();
    c.innerHTML = DOMPurify.sanitize(marked.parse(md));
    c.scrollTop = 0;
  } catch (e) {
    c.innerHTML = `<p class="muted">Failed: ${escapeHtml(e.message)}</p>`;
  }
}

$("#rescan-btn").addEventListener("click", async () => {
  await api("/api/rescan", { method: "POST" });
  await loadTargets();
});

$("#targets-filter").addEventListener("input", renderTargets);

$("#targets-list").addEventListener("change", async (e) => {
  if (!e.target.matches('input[type="checkbox"]')) return;
  const name = e.target.dataset.name;
  const enabled = e.target.checked;
  const t = _targets.find((x) => x.name === name);
  if (t) t.enabled = enabled;
  e.target.closest("label").classList.toggle("disabled", !enabled);
  $("#targets-summary").textContent = `${_targets.filter((t) => t.enabled).length} / ${_targets.length} enabled`;
  await api("/api/targets/toggle", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ updates: { [name]: enabled } }),
  });
});

$("#run-btn").addEventListener("click", async () => {
  const project = $("#project-select").value;
  const tasks = [...document.querySelectorAll(".tasks input:checked")].map((i) => i.value);
  if (!project || !tasks.length) return;
  const btn = $("#run-btn");
  btn.disabled = true;
  $("#run-status").textContent = `Running ${tasks.join(", ")} on ${project}…`;
  try {
    const r = await api("/api/audit", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project, tasks }),
    });
    const ok = r.results.filter((x) => x.success).length;
    $("#run-status").textContent = `Done: ${ok}/${r.results.length} succeeded.`;
    await loadReports();
  } catch (e) {
    $("#run-status").textContent = `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
  }
});

document.addEventListener("click", (e) => {
  const link = e.target.closest("[data-project][data-file]");
  if (link) { e.preventDefault(); openReport(link.dataset.project, link.dataset.file); return; }
  if (e.target.matches("[data-close]")) $("#report-modal").classList.add("hidden");
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("#report-modal").classList.add("hidden");
});

(async () => {
  await loadHealth();
  await loadTargets();
  await loadReports();
})();
