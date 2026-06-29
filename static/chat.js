// Case-bound intake chat ("Echo"). Persists to the DB; the Case Record panel
// updates from structured extraction after each exchange.

const $ = (id) => document.getElementById(id);

const state = {
  caseId: null,
  submitThreshold: 80,
  competencies: [],
};

function fmtSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

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
  state.competencies = comps;
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

  renderEvidence(rec.evidence || [], comps);

  // submit gating + composer lock for non-draft cases
  const isDraft = c.status === "Draft";
  const canSubmit = pct >= state.submitThreshold && isDraft;
  $("submitReview").disabled = !canSubmit;
  $("submitReview").hidden = !isDraft;
  $("submitHint").textContent = isDraft
    ? (canSubmit ? "Your case is ready to submit." : `Reach ${state.submitThreshold}% to submit (currently ${pct}%).`)
    : `This case is ${c.status.toLowerCase()} and is now read-only.`;
  ["msg", "send", "attachBtn", "targetCourse", "summary"].forEach((id) => {
    const el = $(id); if (el) el.disabled = !isDraft;
  });
}

function labelFor(status) {
  return { mapped: "Mapped", needs_review: "Needs Review", unlinked: "Unlinked" }[status] || "Unlinked";
}

function renderEvidence(evidence, comps) {
  const el = $("evidence");
  if (!evidence.length) {
    el.innerHTML = '<p class="muted-empty">No evidence yet. Attach a file or drag one here.</p>';
    return;
  }
  el.innerHTML = "";
  evidence.forEach((ev) => {
    const item = document.createElement("div");
    item.className = "evidence-item";
    item.dataset.status = ev.mapping_status || "unlinked";

    const compName = (comps.find((c) => c.id === ev.competency_id) || {}).name;
    const options = comps.map((c) =>
      `<option value="${c.id}" ${c.id === ev.competency_id ? "selected" : ""}>${escapeHtml(c.name)}</option>`).join("");

    let suggestionHtml = "";
    if (ev.mapping_status !== "mapped" && ev.ai_suggested_competency) {
      suggestionHtml = `<div class="suggestion">Suggested: <b>${escapeHtml(ev.ai_suggested_competency)}</b>
        <button class="linklike" data-accept="${ev.id}" data-name="${escapeHtml(ev.ai_suggested_competency)}">Accept</button></div>`;
    }

    item.innerHTML = `
      <div class="ev-head">
        <span class="ev-name">${escapeHtml(ev.filename)}</span>
        <span class="ev-size mono">${fmtSize(ev.size_bytes || 0)}</span>
      </div>
      <span class="comp-state">${labelFor(ev.mapping_status)}${compName ? " · " + escapeHtml(compName) : ""}</span>
      ${suggestionHtml}
      <div class="ev-actions">
        <select data-link="${ev.id}" aria-label="Link to competency">
          <option value="">— link to competency —</option>${options}
        </select>
        ${ev.competency_id ? `<button class="smallbtn" data-unlink="${ev.id}">Unlink</button>` : ""}
        <a class="smallbtn" href="/api/evidence/${ev.id}/download" target="_blank" rel="noopener">View</a>
        <button class="smallbtn danger-btn" data-del="${ev.id}">Delete</button>
      </div>`;
    el.appendChild(item);
  });
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
    // Persist local browser identity (cleared by "Reset Student Session").
    try { localStorage.setItem("cpl_identity", JSON.stringify({ name, nuid })); } catch (_) {}
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

$("submitReview").addEventListener("click", async () => {
  if (!confirm("Submit this case for faculty review? You won't be able to edit it after.")) return;
  $("submitReview").disabled = true;
  try {
    const rec = await api(`/api/cases/${state.caseId}/submit`, { method: "POST" });
    renderRecord(rec);
    appendMessage("system",
      `Case submitted for review. AI confidence: ${rec.case.ai_confidence ?? "—"}%. ` +
      `A reviewer will follow up with a decision.`);
  } catch (e) {
    appendMessage("system", `Could not submit: ${e.message}`);
    $("submitReview").disabled = false;
  }
});

// ---------- init: resume existing case or prefill identity ----------
(async function init() {
  const params = new URLSearchParams(location.search);
  const resumeId = params.get("case");
  if (resumeId) {
    try {
      const rec = await api(`/api/cases/${resumeId}`);
      state.caseId = rec.case.id;
      $("identityGate").hidden = true;
      $("workspace").hidden = false;
      renderRecord(rec);
      const t = await api(`/api/cases/${resumeId}/transcript`);
      t.messages.filter((m) => m.role !== "system").forEach((m) =>
        appendMessage(m.role === "user" ? "user" : "ai", m.content));
      appendMessage("system", `Resumed case ${rec.case.case_code}.`);
      $("msg").focus();
      return;
    } catch (e) { /* fall through to gate */ }
  }
  try {
    const id = JSON.parse(localStorage.getItem("cpl_identity") || "null");
    if (id) { $("nameInput").value = id.name || ""; $("nuidInput").value = id.nuid || ""; }
  } catch (_) {}
})();

// ---------- evidence ----------
async function uploadEvidence(file) {
  if (!file || !state.caseId) return;
  setStatus("Uploading…");
  const note = appendMessage("system", `Uploading ${file.name}…`);
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await fetch(`/api/cases/${state.caseId}/evidence`, { method: "POST", body: fd });
    const data = await res.json();
    note.remove();
    if (!res.ok) { appendMessage("system", `Upload failed: ${data.error}`); return; }
    renderRecord(data);
    appendMessage("system", data.suggestion
      ? `Added ${file.name}. Echo suggests linking it to “${data.suggestion}.”`
      : `Added ${file.name}.`);
  } catch (e) {
    note.remove();
    appendMessage("system", `Upload error: ${e.message}`);
  } finally {
    setStatus("Ready");
  }
}

$("attachBtn").addEventListener("click", () => $("fileUpload").click());
$("fileUpload").addEventListener("change", (e) => {
  if (e.target.files[0]) uploadEvidence(e.target.files[0]);
  e.target.value = "";
});

// drag-and-drop onto the Case Record panel
const recordPane = document.querySelector(".pane-record");
if (recordPane) {
  ["dragover", "dragenter"].forEach((ev) =>
    recordPane.addEventListener(ev, (e) => { e.preventDefault(); recordPane.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((ev) =>
    recordPane.addEventListener(ev, (e) => { e.preventDefault(); recordPane.classList.remove("dragging"); }));
  recordPane.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files[0];
    if (f) uploadEvidence(f);
  });
}

// delegated evidence actions
$("evidence").addEventListener("click", async (e) => {
  const t = e.target;
  if (t.dataset.accept) return mapEvidence(t.dataset.accept, findCompId(t.dataset.name));
  if (t.dataset.unlink) return evidenceAction(`/api/evidence/${t.dataset.unlink}/unlink`, "POST");
  if (t.dataset.del) {
    if (confirm("Delete this evidence file?"))
      return evidenceAction(`/api/evidence/${t.dataset.del}`, "DELETE");
  }
});
$("evidence").addEventListener("change", (e) => {
  if (e.target.dataset.link && e.target.value)
    mapEvidence(e.target.dataset.link, e.target.value);
});

function findCompId(name) {
  const c = state.competencies.find((x) => x.name === name);
  return c ? c.id : null;
}

async function mapEvidence(eid, compId) {
  if (!compId) return;
  try {
    const rec = await api(`/api/evidence/${eid}/link`, {
      method: "POST", body: JSON.stringify({ competency_id: Number(compId) }),
    });
    renderRecord(rec);
  } catch (e) { setStatus("Link failed"); }
}

async function evidenceAction(url, method) {
  try {
    const rec = await api(url, { method });
    renderRecord(rec);
  } catch (e) { setStatus("Action failed"); }
}
