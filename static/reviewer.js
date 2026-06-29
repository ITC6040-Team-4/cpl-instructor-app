// Reviewer Case Queue — filter tabs with counts, search, sort, CSV export.
const $ = (id) => document.getElementById(id);

const state = { filter: "all", q: "", sort: "ai_confidence", dir: -1, cases: [] };

function esc(s) {
  return (s || "").replace(/[&<>"']/g, (m) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

async function load() {
  const res = await fetch(`/api/reviewer/cases?status=${state.filter}&q=${encodeURIComponent(state.q)}`);
  if (res.status === 401) { location.href = "/reviewer/login"; return; }
  const data = await res.json();
  state.cases = data.cases || [];
  Object.entries(data.counts || {}).forEach(([k, v]) => {
    const el = document.querySelector(`[data-count="${k}"]`);
    if (el) el.textContent = v;
  });
  render();
}

function confidenceDial(v) {
  if (v == null) return '<span class="muted-date">—</span>';
  const hue = v >= 70 ? "#2E5E54" : v >= 45 ? "#C08A2D" : "#B4502E";
  return `<span class="mini-dial" style="--pct:${v};--c:${hue}"></span><span class="mono">${v}</span>`;
}

function statusTag(s) {
  return `<span class="status-tag" data-status="${(s || "").toLowerCase().replace(/\s+/g, "-")}">${esc(s)}</span>`;
}

function render() {
  const rows = [...state.cases].sort((a, b) => {
    let x = a[state.sort], y = b[state.sort];
    if (x == null) x = -Infinity; if (y == null) y = -Infinity;
    if (typeof x === "string") return state.dir * x.localeCompare(y);
    return state.dir * (x - y);
  });
  const body = $("queueBody");
  $("queueEmpty").hidden = rows.length > 0;
  body.innerHTML = rows.map((c) => `
    <tr data-open="${c.id}">
      <td class="mono">${esc(c.case_code)}</td>
      <td>${esc(c.applicant_name || "—")}</td>
      <td>${esc(c.target_course || "—")}</td>
      <td>${statusTag(c.status)}</td>
      <td class="mono">${c.completion_pct || 0}%</td>
      <td class="conf-cell">${confidenceDial(c.ai_confidence)}</td>
      <td class="muted-date">${esc((c.updated_at || "").replace("T", " ").replace("Z", ""))}</td>
      <td><button class="smallbtn" data-open="${c.id}">Open</button></td>
    </tr>`).join("");
}

// events
$("filterTabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab"); if (!btn) return;
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  btn.classList.add("active");
  state.filter = btn.dataset.filter;
  load();
});

let searchTimer;
$("search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.q = e.target.value; load(); }, 250);
});

document.querySelector(".queue-table thead").addEventListener("click", (e) => {
  const th = e.target.closest("th[data-sort]"); if (!th) return;
  const key = th.dataset.sort;
  state.dir = state.sort === key ? -state.dir : -1;
  state.sort = key;
  render();
});

$("queueBody").addEventListener("click", (e) => {
  const id = e.target.closest("[data-open]")?.dataset.open;
  if (id) location.href = `/reviewer/case/${id}`;
});

$("exportBtn").addEventListener("click", (e) => {
  e.preventDefault();
  location.href = `/api/reviewer/cases.csv?status=${state.filter}&q=${encodeURIComponent(state.q)}`;
});

$("logoutBtn").addEventListener("click", async () => {
  await fetch("/api/reviewer/logout", { method: "POST" });
  location.href = "/reviewer/login";
});

load();
