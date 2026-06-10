const $ = (s) => document.querySelector(s);
let _targets = [];

// Dashboard auth token, read once from the page URL (?token=...). When
// AUDITOR_TOKEN is set server-side, every /api/* call must carry it as a
// Bearer header or the gate returns 401. Empty string in loopback mode.
const _token = new URL(location.href).searchParams.get("token") || "";

function _authHeaders(extra) {
  const h = { ...(extra || {}) };
  if (_token) h["Authorization"] = `Bearer ${_token}`;
  return h;
}

async function api(url, opts) {
  const o = { ...(opts || {}) };
  o.headers = _authHeaders(o.headers);
  const r = await fetch(url, o);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

async function loadHealth() {
  try {
    await api("/api/health");
    $("#repos-pill").textContent = "online";
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
  _targets.filter((t) => t.enabled).forEach((t) => {
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
    const r = await fetch(
      `/api/report?project=${encodeURIComponent(project)}&file=${encodeURIComponent(file)}`,
      { headers: _authHeaders() },
    );
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
  await loadTargets();
});

// Current running job (one at a time from this UI). Held so Cancel works.
let _currentJob = null;
let _currentSource = null;

function _cancelCurrentJob() {
  if (!_currentJob) return;
  fetch(`/api/audit/${encodeURIComponent(_currentJob)}`, { method: "DELETE", headers: _authHeaders() })
    .catch(() => {});
}

$("#run-btn").addEventListener("click", async () => {
  const project = $("#project-select").value;
  const tasks = [...document.querySelectorAll(".tasks input:checked")].map((i) => i.value);
  if (!project || !tasks.length) return;
  const btn = $("#run-btn");
  const cancelBtn = $("#cancel-btn");
  btn.disabled = true;
  $("#run-status").textContent = `Queuing ${tasks.join(", ")} on ${project}…`;

  let job;
  try {
    job = await api("/api/audit", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project, tasks }),
    });
  } catch (e) {
    $("#run-status").textContent = `Error: ${e.message}`;
    btn.disabled = false;
    return;
  }

  _currentJob = job.job_id;
  if (cancelBtn) cancelBtn.hidden = false;
  $("#run-status").textContent = `Started job ${job.job_id} — listening for progress…`;

  // SSE auth uses the query token (EventSource can't set Authorization
  // headers). Falls back to no token in loopback mode.
  const src = new EventSource(`/api/audit/${encodeURIComponent(job.job_id)}/events?token=${encodeURIComponent(_token)}`);
  _currentSource = src;

  src.onmessage = (m) => {
    let ev;
    try { ev = JSON.parse(m.data); } catch { return; }
    const done = (ev.tasks || []).filter((x) => x.status === "done").length;
    const total = (ev.tasks || []).length;
    if (ev.type === "task_started") {
      $("#run-status").textContent = `Running ${ev.task} (${done}/${total} done)…`;
    } else if (ev.type === "task_done") {
      $("#run-status").textContent = `${ev.task} → ${ev.tasks.find((x) => x.task === ev.task)?.status}; ${done}/${total} done`;
    } else if (ev.type === "job_ended" || ev.status === "done" || ev.status === "cancelled" || ev.status === "failed") {
      const ok = (ev.tasks || []).filter((x) => x.status === "done").length;
      $("#run-status").textContent = `Job ${ev.status}: ${ok}/${(ev.tasks || []).length} succeeded.`;
      src.close();
      _currentSource = null;
      _currentJob = null;
      if (cancelBtn) cancelBtn.hidden = true;
      btn.disabled = false;
      loadReports();
    }
  };
  src.onerror = () => {
    src.close();
    _currentSource = null;
    _currentJob = null;
    if (cancelBtn) cancelBtn.hidden = true;
    btn.disabled = false;
    $("#run-status").textContent += " (event stream closed)";
  };
});

document.addEventListener("click", (e) => {
  if (e.target && e.target.id === "cancel-btn") _cancelCurrentJob();
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
