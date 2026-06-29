// Learner portfolio history — list by NU-ID, detail drawer, continue/delete/feedback.
const $ = (id) => document.getElementById(id);

function esc(s) {
  return (s || "").replace(/[&<>"']/g, (m) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

async function api(url, opts = {}) {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opts });
  const text = await res.text();
  let data = null; try { data = JSON.parse(text); } catch (_) {}
  if (!res.ok) throw new Error((data && data.error) || "Request failed");
  return data;
}

function statusTag(s) {
  return `<span class="status-tag" data-status="${(s || "").toLowerCase().replace(/\s+/g, "-")}">${esc(window.statusLabel(s))}</span>`;
}

let currentNuid = "";

async function lookup() {
  const nuid = $("nuidInput").value.trim();
  if (!nuid) return;
  currentNuid = nuid;
  try { localStorage.setItem("cpl_identity", JSON.stringify({ ...(JSON.parse(localStorage.getItem("cpl_identity") || "{}")), nuid })); } catch (_) {}
  const data = await api(`/api/cases?nuid=${encodeURIComponent(nuid)}`);
  $("idGate").hidden = true;
  $("listCard").hidden = false;
  renderList(data.cases || []);
}

function renderList(cases) {
  const el = $("caseList");
  if (!cases.length) {
    el.innerHTML = `<div class="empty-state">
      <p class="empty-title">No portfolios yet</p>
      <p class="empty-sub">Tell Vera about your experience to start your first one — it only takes a few minutes.</p>
      <a href="/chat" class="primary as-btn">Start your first portfolio →</a>
    </div>`;
    return;
  }
  el.innerHTML = "";
  cases.forEach((c) => {
    const row = document.createElement("div");
    row.className = "case-row";
    row.innerHTML = `
      <div class="case-row-main">
        <span class="case-code mono">${esc(c.case_code)}</span>
        <span class="case-course">${esc(c.target_course || "No target course yet")}</span>
      </div>
      <div class="case-row-meta">
        ${statusTag(c.status)}
        <span class="mono">${c.completion_pct || 0}%</span>
        <span class="muted-date">${esc((c.updated_at || "").replace("T", " ").replace("Z", ""))}</span>
        <button class="smallbtn" data-detail="${c.id}">Open</button>
      </div>`;
    el.appendChild(row);
  });
}

async function openDetail(id) {
  const d = await api(`/api/cases/${id}/detail`);
  const c = d.case;
  const fb = d.feedback;
  const isDraft = c.status === "Draft";
  const decisionLabel = { approve: "Credit awarded", deny: "Credit declined", revise: "Returned for revision" };

  const competencyHtml = (d.competencies || []).map((x) =>
    `<li><b>${esc(x.name)}</b> <span class="comp-state">${esc(x.mapping_status)}</span></li>`).join("") || "<li class='muted-empty'>None</li>";

  $("detailBody").innerHTML = `
    <div class="record-head">
      <div><div class="case-code mono">${esc(c.case_code)}</div>${statusTag(c.status)}</div>
      <div class="dial" style="--pct:${c.completion_pct || 0}"><span class="dial-pct mono">${c.completion_pct || 0}%</span></div>
    </div>
    <p class="detail-label">Target course</p><p>${esc(c.target_course || "—")}</p>
    <p class="detail-label">Summary</p><p>${esc(c.summary || "—")}</p>
    <p class="detail-label">Claims</p><ul class="detail-list">${competencyHtml}</ul>
    ${fb ? `<div class="feedback-box">
       <p class="detail-label">Assessor feedback — ${esc(decisionLabel[fb.decision] || fb.decision)}</p>
       <p>${esc(fb.notes || "No notes provided.")}</p></div>` : ""}
    <div class="ev-actions" style="margin-top:16px">
      ${isDraft
        ? `<a class="primary as-btn" href="/chat?case=${c.id}">Continue conversation</a>`
        : `<a class="smallbtn" href="/chat?case=${c.id}">View conversation</a>`}
      <button class="smallbtn" data-advisor="${c.id}">Message an assessor</button>
      ${isDraft ? `<button class="smallbtn danger-btn" data-del="${c.id}">Delete portfolio</button>` : ""}
    </div>`;
  $("detailModal").hidden = false;
}

// events
$("lookupBtn").addEventListener("click", lookup);
$("nuidInput").addEventListener("keydown", (e) => { if (e.key === "Enter") lookup(); });
$("modalClose").addEventListener("click", () => ($("detailModal").hidden = true));
$("detailModal").addEventListener("click", (e) => { if (e.target.id === "detailModal") $("detailModal").hidden = true; });

$("caseList").addEventListener("click", (e) => {
  if (e.target.dataset.detail) openDetail(e.target.dataset.detail);
});
$("detailBody").addEventListener("click", async (e) => {
  if (e.target.dataset.del) {
    if (!confirm("Delete this portfolio permanently?")) return;
    try {
      await api(`/api/cases/${e.target.dataset.del}`, { method: "DELETE" });
      $("detailModal").hidden = true;
      lookup();
    } catch (err) { alert(err.message); }
  }
  if (e.target.dataset.advisor) {
    alert("An assessor will be notified. (Messaging reuses the existing submit-for-assessment path.)");
  }
});

// prefill from local identity
(function init() {
  try {
    const id = JSON.parse(localStorage.getItem("cpl_identity") || "null");
    if (id && id.nuid) { $("nuidInput").value = id.nuid; lookup(); }
  } catch (_) {}
})();
