// App shell: ⌘K command palette, role-aware actions, queue badge, system links.
// Self-contained — injects its own DOM, needs no markup on the host page.
(function () {
  const ACTIONS_BASE = [
    { label: "New case", hint: "Start an evaluation", href: "/chat", icon: "✦" },
    { label: "Case History", hint: "Your submitted cases", href: "/history", icon: "❏" },
    { label: "Case Queue", hint: "Review submitted cases", href: "/reviewer", icon: "⚖", reviewer: true },
    { label: "Settings", hint: "Thresholds, guardrails, catalog", href: "/reviewer/settings", icon: "⚙", reviewer: true },
    { label: "Sign in as reviewer", hint: "Faculty / advisor portal", href: "/reviewer/login", icon: "→", guestOnly: true },
    { label: "Config Status", hint: "Environment configuration", href: "/admin", icon: "·" },
    { label: "Health Check", hint: "/health", href: "/health", icon: "·" },
    { label: "DB Check", hint: "/dbcheck", href: "/dbcheck", icon: "·" },
  ];

  let ctx = { authenticated: false, counts: {} };
  let overlay, input, list, paletteOpen = false;

  function actions() {
    return ACTIONS_BASE.filter((a) =>
      (!a.reviewer || ctx.authenticated) && (!a.guestOnly || !ctx.authenticated))
      .map((a) => {
        if (a.href === "/reviewer" && ctx.counts.needs_review)
          return { ...a, badge: ctx.counts.needs_review };
        return a;
      });
  }

  function build() {
    overlay = document.createElement("div");
    overlay.className = "cmdk-overlay";
    overlay.hidden = true;
    overlay.innerHTML = `
      <div class="cmdk" role="dialog" aria-modal="true" aria-label="Command palette">
        <input class="cmdk-input" type="text" placeholder="Type a command or search a case…" aria-label="Command palette search" />
        <div class="cmdk-list" role="listbox"></div>
        <div class="cmdk-foot"><span>↑↓ navigate · ↵ open · esc close</span></div>
      </div>`;
    document.body.appendChild(overlay);
    input = overlay.querySelector(".cmdk-input");
    list = overlay.querySelector(".cmdk-list");

    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    input.addEventListener("input", () => renderList(input.value));
    input.addEventListener("keydown", onKey);
  }

  let caseResults = [];
  let searchTimer;
  function renderList(q) {
    q = (q || "").trim().toLowerCase();
    const acts = actions().filter((a) =>
      !q || a.label.toLowerCase().includes(q) || (a.hint || "").toLowerCase().includes(q));
    let html = acts.map((a, i) => row(a.icon, a.label, a.hint, a.href, i === 0 && !caseResults.length, a.badge)).join("");
    if (caseResults.length) {
      html += `<div class="cmdk-section">Cases</div>` + caseResults.map((c, i) =>
        row("▸", c.case_code + " · " + (c.applicant_name || ""), c.target_course || "",
            ctx.authenticated ? `/reviewer/case/${c.id}` : `/chat?case=${c.id}`, false)).join("");
    }
    list.innerHTML = html || '<div class="cmdk-empty">No matches.</div>';

    // live case search for reviewers
    if (ctx.authenticated && q.length >= 2) {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(async () => {
        try {
          const d = await (await fetch(`/api/reviewer/cases?q=${encodeURIComponent(q)}`)).json();
          caseResults = (d.cases || []).slice(0, 5);
          if (paletteOpen) renderList(input.value);
        } catch (_) {}
      }, 220);
    } else if (caseResults.length && q.length < 2) {
      caseResults = [];
    }
  }

  function row(icon, label, hint, href, active, badge) {
    return `<a class="cmdk-row ${active ? "active" : ""}" href="${href}" role="option">
      <span class="cmdk-icon">${icon}</span>
      <span class="cmdk-label">${label}${badge ? ` <span class="cmdk-badge">${badge}</span>` : ""}</span>
      <span class="cmdk-hint">${hint || ""}</span></a>`;
  }

  function onKey(e) {
    const rows = [...list.querySelectorAll(".cmdk-row")];
    const cur = list.querySelector(".cmdk-row.active");
    let idx = rows.indexOf(cur);
    if (e.key === "ArrowDown") { e.preventDefault(); move(rows, idx, 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(rows, idx, -1); }
    else if (e.key === "Enter") { e.preventDefault(); if (cur) location.href = cur.getAttribute("href"); }
    else if (e.key === "Escape") { close(); }
  }
  function move(rows, idx, d) {
    if (!rows.length) return;
    rows.forEach((r) => r.classList.remove("active"));
    const n = (idx + d + rows.length) % rows.length;
    rows[n].classList.add("active");
    rows[n].scrollIntoView({ block: "nearest" });
  }

  function open() { caseResults = []; overlay.hidden = false; paletteOpen = true; input.value = ""; renderList(""); input.focus(); }
  function close() { overlay.hidden = true; paletteOpen = false; }

  // global hotkey
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
      e.preventDefault(); paletteOpen ? close() : open();
    }
  });

  // expose a launcher + role switcher hook
  window.CPLShell = { open, setContext: (c) => { ctx = { ...ctx, ...c }; } };

  async function init() {
    build();
    try {
      const me = await (await fetch("/api/reviewer/me")).json();
      ctx.authenticated = !!me.authenticated;
      ctx.counts = me.counts || {};
    } catch (_) {}
    // update any queue badges on the page
    document.querySelectorAll("[data-queue-badge]").forEach((el) => {
      const n = ctx.counts.needs_review || 0;
      el.textContent = n;
      el.hidden = !n;
    });
    document.dispatchEvent(new CustomEvent("cpl-shell-ready", { detail: ctx }));
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
