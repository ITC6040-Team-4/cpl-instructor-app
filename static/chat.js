// Case-bound intake chat ("Echo"). Persists to the DB; the Case Record panel
// updates from structured extraction after each exchange.

const $ = (id) => document.getElementById(id);

const state = {
  caseId: null,
  submitThreshold: 80,
};

// ---------- helpers ----------
function setStatus(text) { $("statusText").textContent = text; }

function appendMessage(role, text) {
  const hist = $("chatHistory");
  const div = document.createElement("div");
  div.className = `msg-bubble msg-${role}`;
  div.textContent = text;
  hist.appendChild(div);
  hist.scrollTop = hist.scrollHeight;
  return div;
}

async function api(url, opts = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch (_) {}
  if (!res.ok) throw new Error((data && data.error) || text || "Request failed");
  return data;
}

// ---------- case record rendering ----------
function renderRecord(rec) {
  const c = rec.case;
  $("caseCode").textContent = c.case_code;
  $("caseStatus").textContent = c.status;
  $("caseStatus").dataset.status = (c.status || "").toLowerCase().replace(/\s+/g, "-");

  const pct = c.completion_pct || 0;
  $("completionPct").textContent = pct + "%";
  $("dial").style.setProperty("--pct", pct);

  // Only overwrite editable fields when the user isn't actively editing them.
  if (document.activeElement !== $("targetCourse"))
    $("targetCourse").value = c.target_course || "";
  if (document.activeElement !== $("summary"))
    $("summary").value = c.summary || "";

  // competencies
  const comps = rec.competencies || [];
  const cl = $("competencies");
  if (!comps.length) {
    cl.innerHTML = '<p class="muted-empty">No competencies claimed yet — keep describing your experience.</p>';
  } else {
    cl.innerHTML = "";
    comps.forEach((comp) => {
      const item = document.createElement("div");
      item.className = "competency-item";
      item.dataset.status = comp.mapping_status || "unlinked";
      item.innerHTML = `<div class="comp-name">${escapeHtml(comp.name)}</div>
        <div class="comp-desc">${escapeHtml(comp.description || "")}</div>
        <span class="comp-state">${labelFor(comp.mapping_status)}</span>`;
      cl.appendChild(item);
    });
  }

  // submit gating
  const canSubmit = pct >= state.submitThreshold && c.status === "Draft";
  $("submitReview").disabled = !canSubmit;
  $("submitHint").textContent = canSubmit
    ? "Your case is ready to submit."
    : `Reach ${state.submitThreshold}% to submit (currently ${pct}%).`;
}

function labelFor(status) {
  return { mapped: "Mapped", needs_review: "Needs Review", unlinked: "Unlinked" }[status] || "Unlinked";
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, (m) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

// ---------- flows ----------
async function startCase() {
  const name = $("nameInput").value.trim();
  const nuid = $("nuidInput").value.trim();
  $("gateError").textContent = "";
  if (!name || !nuid) {
    $("gateError").textContent = "Please enter both your name and NU-ID.";
    return;
  }
  $("startBtn").disabled = true;
  try {
    const rec = await api("/api/cases", { method: "POST", body: JSON.stringify({ name, nuid }) });
    state.caseId = rec.case.id;
    $("identityGate").hidden = true;
    $("workspace").hidden = false;
    renderRecord(rec);
    appendMessage("system", `Case ${rec.case.case_code} opened. Tell Echo about your experience.`);
    $("msg").focus();
  } catch (e) {
    $("gateError").textContent = e.message;
    $("startBtn").disabled = false;
  }
}

async function sendMessage() {
  const text = $("msg").value.trim();
  if (!text || !state.caseId) return;

  appendMessage("user", text);
  $("msg").value = "";
  setBusy(true);
  const thinking = appendMessage("system", "Echo is thinking…");

  try {
    const rec = await api(`/api/cases/${state.caseId}/message`, {
      method: "POST", body: JSON.stringify({ message: text }),
    });
    thinking.remove();
    appendMessage("ai", rec.answer);
    renderRecord(rec);
  } catch (e) {
    thinking.remove();
    appendMessage("system", `Something went wrong: ${e.message}`);
  } finally {
    setBusy(false);
    $("msg").focus();
  }
}

function setBusy(busy) {
  $("send").disabled = busy;
  $("msg").disabled = busy;
  setStatus(busy ? "Thinking…" : "Ready");
}

async function saveField(field, value) {
  try {
    const rec = await api(`/api/cases/${state.caseId}`, {
      method: "PATCH", body: JSON.stringify({ [field]: value }),
    });
    renderRecord(rec);
  } catch (e) {
    setStatus("Save failed");
  }
}

// ---------- wiring ----------
$("startBtn").addEventListener("click", startCase);
[$("nameInput"), $("nuidInput")].forEach((el) =>
  el.addEventListener("keydown", (e) => { if (e.key === "Enter") startCase(); }));

$("send").addEventListener("click", sendMessage);
$("msg").addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); sendMessage(); }
});

$("targetCourse").addEventListener("blur", (e) => saveField("target_course", e.target.value.trim()));
$("summary").addEventListener("blur", (e) => saveField("summary", e.target.value.trim()));

$("copy").addEventListener("click", async () => {
  const transcript = Array.from(document.querySelectorAll("#chatHistory .msg-bubble:not(.msg-system)"))
    .map((el) => (el.classList.contains("msg-user") ? "You:\n" : "Echo:\n") + el.textContent)
    .join("\n\n---\n\n");
  try {
    await navigator.clipboard.writeText(transcript);
    const btn = $("copy"); const old = btn.textContent;
    btn.textContent = "Copied!"; setTimeout(() => (btn.textContent = old), 900);
  } catch { alert("Failed to copy transcript."); }
});

$("submitReview").addEventListener("click", () => {
  alert("Submit for Review unlocks in the next build step.");
});
