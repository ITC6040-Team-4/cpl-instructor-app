// Assessor settings: thresholds, guardrails, routing rules, Reference Library CRUD, demo tools.
const $ = (id) => document.getElementById(id);

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

async function load() {
  const d = await api("/api/settings");
  const s = d.settings;
  $("institution_name").value = s.institution_name || "";
  $("draft_threshold").value = s.draft_threshold;
  $("submit_threshold").value = s.submit_threshold;
  $("delete_below_threshold").value = s.delete_below_threshold;
  $("strict_domain").checked = !!s.strict_domain;
  $("require_evidence_links").checked = !!s.require_evidence_links;
  $("system_prompt_addendum").value = s.system_prompt_addendum || "";
  renderRules(d.routing_rules || []);
  renderCatalog(d.catalog || []);
}

function renderRules(rules) {
  $("rulesList").innerHTML = rules.length ? rules.map((r) => `
    <div class="rule-row">
      <span><b>${esc(r.condition_type.replace("_", " "))}</b> "${esc(r.condition_value)}"
      → <b>${esc(r.action_type)}</b> "${esc(r.action_value)}"</span>
      <button class="smallbtn danger-btn" data-rule="${r.id}">Remove</button>
    </div>`).join("") : '<p class="muted-empty">No rules yet.</p>';
}

function renderCatalog(entries) {
  $("catalogList").innerHTML = entries.length ? entries.map((e) => `
    <div class="catalog-row">
      <div><span class="cat-type">${esc(e.type)}</span> <b class="mono">${esc(e.code || "")}</b> ${esc(e.title)}
        <div class="cat-content">${esc((e.content || "").slice(0, 160))}${(e.content || "").length > 160 ? "…" : ""}</div></div>
      <button class="smallbtn danger-btn" data-catalog="${e.id}">Delete</button>
    </div>`).join("") : '<p class="muted-empty">No library entries yet.</p>';
}

// settings save
$("saveSettings").addEventListener("click", async () => {
  await api("/api/settings", { method: "PUT", body: JSON.stringify({
    institution_name: $("institution_name").value.trim(),
    draft_threshold: $("draft_threshold").value,
    submit_threshold: $("submit_threshold").value,
    delete_below_threshold: $("delete_below_threshold").value,
    strict_domain: $("strict_domain").checked,
    require_evidence_links: $("require_evidence_links").checked,
    system_prompt_addendum: $("system_prompt_addendum").value,
  }) });
  $("settingsSaved").textContent = "Saved ✓";
  setTimeout(() => ($("settingsSaved").textContent = ""), 1800);
});

// routing rules
$("addRule").addEventListener("click", async () => {
  const cv = $("r_condition_value").value.trim(), av = $("r_action_value").value.trim();
  if (!cv || !av) return alert("Enter both a condition and an action value.");
  const d = await api("/api/routing-rules", { method: "POST", body: JSON.stringify({
    condition_type: $("r_condition_type").value, condition_value: cv,
    action_type: $("r_action_type").value, action_value: av,
  }) });
  renderRules(d.routing_rules);
  $("r_condition_value").value = ""; $("r_action_value").value = "";
});
$("rulesList").addEventListener("click", async (e) => {
  if (e.target.dataset.rule) renderRules((await api(`/api/routing-rules/${e.target.dataset.rule}`, { method: "DELETE" })).routing_rules);
});

// catalog
$("addCatalog").addEventListener("click", async () => {
  if (!$("c_title").value.trim()) return alert("Title is required.");
  const d = await api("/api/catalog", { method: "POST", body: JSON.stringify({
    type: $("c_type").value, code: $("c_code").value.trim(),
    title: $("c_title").value.trim(), content: $("c_content").value.trim(),
  }) });
  renderCatalog(d.catalog);
  $("c_code").value = ""; $("c_title").value = ""; $("c_content").value = "";
});
$("catalogList").addEventListener("click", async (e) => {
  if (e.target.dataset.catalog && confirm("Delete this Reference Library entry?"))
    renderCatalog((await api(`/api/catalog/${e.target.dataset.catalog}`, { method: "DELETE" })).catalog);
});

// demo tool
$("resetSession").addEventListener("click", () => {
  try { localStorage.removeItem("cpl_identity"); } catch (_) {}
  alert("Learner session reset. This browser's saved identity was cleared; portfolios remain in the database.");
});

load();
