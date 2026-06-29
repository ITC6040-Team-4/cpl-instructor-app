// Assessor portfolio review: assessment, read-only Intake Record, artifacts, decisions, referral.
const DECISION_LABELS = { approve: "Award", deny: "Decline", revise: "Return" };
const $ = (id) => document.getElementById(id);
const CASE_ID = window.CASE_ID;

function esc(s) {
  return (s || "").replace(/[&<>"']/g, (m) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

async function api(url, opts = {}) {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opts });
  if (res.status === 401) { location.href = "/reviewer/login"; throw new Error("auth"); }
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

let compIndex = {};

function render(d) {
  const c = d.case;
  compIndex = {};
  (d.competencies || []).forEach((x) => (compIndex[x.id] = x.name));

  $("loading").hidden = true;
  $("caseView").hidden = false;
  $("crumbCode").textContent = c.case_code;
  $("caseCode").textContent = c.case_code;
  $("caseStatus").textContent = window.statusLabel(c.status);
  $("caseStatus").dataset.status = (c.status || "").toLowerCase().replace(/\s+/g, "-");
  $("applicant").textContent = `${c.applicant_name || "—"} · NU-ID ${c.applicant_nuid || "—"}`;
  $("targetCourse").textContent = c.target_course || "—";
  $("summary").textContent = c.summary || "—";
  $("rationale").textContent = c.ai_confidence_rationale || "No rationale recorded.";

  const conf = c.ai_confidence;
  $("confPct").textContent = conf == null ? "—" : conf + "%";
  $("confDial").style.setProperty("--pct", conf || 0);

  // transcript (read-only)
  $("transcript").innerHTML = (d.messages || []).map((m) => {
    if (m.role === "system") return `<div class="t-system">${esc(m.content)}</div>`;
    const who = m.role === "user" ? "Learner" : "Vera";
    return `<div class="t-msg t-${m.role}"><span class="t-who">${who}</span>${esc(m.content)}</div>`;
  }).join("") || '<p class="muted-empty">No transcript.</p>';

  // evidence + mappings
  $("evidenceList").innerHTML = (d.evidence || []).map((ev) => `
    <div class="evidence-item" data-status="${ev.mapping_status}">
      <div class="ev-head">
        <span class="ev-name">${esc(ev.filename)}</span>
        <a class="smallbtn" href="/api/evidence/${ev.id}/download" target="_blank" rel="noopener">View</a>
      </div>
      <span class="comp-state">${esc(ev.mapping_status)}${ev.competency_id ? " · " + esc(compIndex[ev.competency_id] || "") : ""}</span>
    </div>`).join("") || '<p class="muted-empty">No artifacts submitted.</p>';

  // decision + escalation history
  const dec = (d.decisions || []).map((x) =>
    `<li><b>${esc(DECISION_LABELS[x.decision] || x.decision)}</b> — ${esc(x.notes || "no notes")} <span class="muted-date">${esc((x.created_at||"").replace("T"," ").replace("Z",""))}</span></li>`).join("");
  const esca = (d.escalations || []).map((x) =>
    `<li><b>Referred: ${esc(x.type)}</b> → ${esc(x.assignee_name || "—")} ${esc(x.assignee_email ? "("+x.assignee_email+")" : "")} — ${esc(x.notes || "")}</li>`).join("");
  $("decisionHistory").innerHTML = (dec || esca)
    ? `<p class="detail-label" style="margin-top:16px;">History</p><ul class="detail-list">${dec}${esca}</ul>` : "";
}

async function load() {
  try { render(await api(`/api/reviewer/cases/${CASE_ID}`)); }
  catch (e) { if (e.message !== "auth") $("loading").innerHTML = `<p class="error">${e.message}</p>`; }
}

async function decide(decision) {
  const labels = { approve: "award credit for", deny: "decline", revise: "return for revision" };
  if (!confirm(`Are you sure you want to ${labels[decision]} this portfolio?`)) return;
  try {
    render(await api(`/api/reviewer/cases/${CASE_ID}/decision`, {
      method: "POST", body: JSON.stringify({ decision, notes: $("notes").value.trim() }),
    }));
    toast(decision === "approve" ? "Credit awarded." : decision === "deny" ? "Credit declined." : "Portfolio returned for revision.");
  } catch (e) { alert(e.message); }
}

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

// events
document.querySelector(".decision-bar").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-decision]");
  if (btn) decide(btn.dataset.decision);
});
$("escalateBtn").addEventListener("click", () => ($("escModal").hidden = false));
$("escClose").addEventListener("click", () => ($("escModal").hidden = true));
$("escModal").addEventListener("click", (e) => { if (e.target.id === "escModal") $("escModal").hidden = true; });
$("escSubmit").addEventListener("click", async () => {
  try {
    render(await api(`/api/reviewer/cases/${CASE_ID}/escalate`, {
      method: "POST", body: JSON.stringify({
        type: $("escType").value, assignee_name: $("escName").value.trim(),
        assignee_email: $("escEmail").value.trim(), notes: $("escNotes").value.trim(),
      }),
    }));
    $("escModal").hidden = true;
    toast("Portfolio referred.");
  } catch (e) { alert(e.message); }
});

load();
