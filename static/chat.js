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

  const comps = rec.competencies || [];
  state.competencies = comps;
  renderCompetencyMap(comps, rec.evidence || []);

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

// The Competency Map: each competency is a slot; mapped evidence cards nest
// inside their slot. Unlinked / suggested evidence waits in the unsorted tray.
function renderCompetencyMap(comps, evidence) {
  const map = $("competencyMap");
  const tray = $("unsortedEvidence");

  if (!comps.length) {
    map.innerHTML = '<p class="muted-empty">No competencies yet — keep describing your experience and they\'ll appear here as slots.</p>';
  } else {
    map.innerHTML = comps.map((comp) => {
      const mapped = evidence.filter((e) => e.competency_id === comp.id);
      const filled = comp.mapping_status === "mapped";
      const cards = mapped.map((e) => evidenceCard(e, true)).join("");
      return `<div class="comp-slot ${filled ? "filled" : ""}" data-status="${comp.mapping_status || "unlinked"}">
        <div class="slot-head">
          <span class="slot-name">${escapeHtml(comp.name)}</span>
          <span class="slot-state">${filled ? "✓ Mapped" : "Open slot"}</span>
        </div>
        ${comp.description ? `<div class="slot-desc">${escapeHtml(comp.description)}</div>` : ""}
        <div class="slot-evidence">${cards || '<span class="slot-empty">No evidence linked yet</span>'}</div>
      </div>`;
    }).join("");
  }

  const unsorted = evidence.filter((e) => !e.competency_id);
  if (!unsorted.length) {
    tray.innerHTML = '<p class="muted-empty">All evidence is linked. Attach or drag a new file to add more.</p>';
  } else {
    tray.innerHTML = unsorted.map((ev) => {
      const options = comps.map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join("");
      const suggestion = ev.ai_suggested_competency
        ? `<div class="suggestion">Echo suggests <b>${escapeHtml(ev.ai_suggested_competency)}</b>
            <button class="linklike" data-accept="${ev.id}" data-name="${escapeHtml(ev.ai_suggested_competency)}">Accept</button></div>` : "";
      return `<div class="evidence-item" data-status="${ev.mapping_status || "unlinked"}" draggable="false">
        <div class="ev-head"><span class="ev-name">${escapeHtml(ev.filename)}</span>
          <span class="ev-size mono">${fmtSize(ev.size_bytes || 0)}</span></div>
        ${suggestion}
        <div class="ev-actions">
          <select data-link="${ev.id}" aria-label="Link to competency">
            <option value="">— link to competency —</option>${options}</select>
          <a class="smallbtn" href="/api/evidence/${ev.id}/download" target="_blank" rel="noopener">View</a>
          <button class="smallbtn danger-btn" data-del="${ev.id}">Delete</button>
        </div></div>`;
    }).join("");
  }
}

function evidenceCard(ev, withUnlink) {
  return `<div class="ev-card">
    <span class="ev-card-name">${escapeHtml(ev.filename)}</span>
    <span class="ev-card-actions">
      <a href="/api/evidence/${ev.id}/download" target="_blank" rel="noopener" title="View">↗</a>
      ${withUnlink ? `<button data-unlink="${ev.id}" title="Unlink">×</button>` : ""}
    </span></div>`;
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
  // Load real thresholds from settings so gating matches admin config.
  try {
    const ps = await (await fetch("/api/public-settings")).json();
    if (ps.submit_threshold != null) state.submitThreshold = ps.submit_threshold;
  } catch (_) {}

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

// delegated evidence actions across the Competency Map + unsorted tray
recordPane.addEventListener("click", async (e) => {
  const t = e.target.closest("[data-accept],[data-unlink],[data-del]");
  if (!t) return;
  if (t.dataset.accept) return mapEvidence(t.dataset.accept, findCompId(t.dataset.name));
  if (t.dataset.unlink) return evidenceAction(`/api/evidence/${t.dataset.unlink}/unlink`, "POST");
  if (t.dataset.del && confirm("Delete this evidence file?"))
    return evidenceAction(`/api/evidence/${t.dataset.del}`, "DELETE");
});
recordPane.addEventListener("change", (e) => {
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
