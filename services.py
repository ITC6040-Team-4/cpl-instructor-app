"""
Case service layer: lifecycle, persistence helpers, deterministic completion,
extraction merge, settings, and catalog grounding retrieval.

Keeps route handlers thin and keeps the completion rubric transparent and in
code (the LLM contributes data, but the percentage is a rubric users can trust).
"""

import db

SUMMARY_MIN_CHARS = 80

STATUS_DRAFT = "Draft"
STATUS_SUBMITTED = "Submitted"
STATUS_IN_REVIEW = "In Review"
STATUS_APPROVED = "Approved"
STATUS_DENIED = "Denied"
STATUS_REVISION = "Revision Requested"
STATUS_ESCALATED = "Escalated"


# ---------------------------------------------------------------------------
# Settings & catalog
# ---------------------------------------------------------------------------
def get_settings():
    s = db.query_one("SELECT * FROM settings WHERE id = 1")
    return s or {
        "institution_name": "NUPathway", "draft_threshold": 25,
        "submit_threshold": 80, "delete_below_threshold": 50,
        "strict_domain": 1, "require_evidence_links": 1,
        "system_prompt_addendum": "",
    }


def update_settings(fields):
    allowed = ["institution_name", "draft_threshold", "submit_threshold",
               "delete_below_threshold", "strict_domain", "require_evidence_links",
               "system_prompt_addendum"]
    sets, params = [], []
    for k in allowed:
        if k in fields:
            sets.append(f"{k} = ?")
            params.append(fields[k])
    if not sets:
        return
    params.append(db.now_iso())
    db.execute(f"UPDATE settings SET {', '.join(sets)}, updated_at = ? WHERE id = 1", params)


def get_catalog(relevant_to=None, limit=6):
    """Return catalog entries; if relevant_to text is given, rank by naive overlap."""
    rows = db.query("SELECT * FROM catalog ORDER BY id")
    if not relevant_to or len(rows) <= limit:
        return rows[:limit] if limit else rows
    terms = {w for w in _tokens(relevant_to) if len(w) > 3}
    def score(r):
        hay = _tokens(f"{r.get('code','')} {r.get('title','')} {r.get('content','')}")
        return len(terms & set(hay))
    return sorted(rows, key=score, reverse=True)[:limit]


def _tokens(text):
    return [t.lower() for t in "".join(
        c if c.isalnum() else " " for c in (text or "")).split()]


# ---------------------------------------------------------------------------
# Case lifecycle
# ---------------------------------------------------------------------------
def next_case_code():
    year = db.now_iso()[:4]
    row = db.query_one("SELECT COUNT(*) AS c FROM cases")
    seq = (row["c"] if row else 0) + 1
    code = f"PLA-{year}-{seq:04d}"
    # guarantee uniqueness in the unlikely event of a gap/race
    while db.query_one("SELECT id FROM cases WHERE case_code = ?", [code]):
        seq += 1
        code = f"PLA-{year}-{seq:04d}"
    return code


def create_case(name, nuid):
    now = db.now_iso()
    code = next_case_code()
    case_id = db.insert(
        """INSERT INTO cases
           (case_code, applicant_name, applicant_nuid, status, completion_pct,
            summary, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [code, name, nuid, STATUS_DRAFT, 0, "", now, now],
    )
    return get_case(case_id)


def get_case(case_id):
    return db.query_one("SELECT * FROM cases WHERE id = ?", [case_id])


def get_case_by_code(code):
    return db.query_one("SELECT * FROM cases WHERE case_code = ?", [code])


def list_cases_by_nuid(nuid):
    return db.query(
        "SELECT * FROM cases WHERE applicant_nuid = ? ORDER BY updated_at DESC", [nuid])


def latest_draft_for(nuid):
    return db.query_one(
        "SELECT * FROM cases WHERE applicant_nuid = ? AND status = ? "
        "ORDER BY updated_at DESC", [nuid, STATUS_DRAFT])


def update_case(case_id, fields):
    if not fields:
        return
    sets, params = [], []
    for k, v in fields.items():
        sets.append(f"{k} = ?")
        params.append(v)
    sets.append("updated_at = ?")
    params.append(db.now_iso())
    params.append(case_id)
    db.execute(f"UPDATE cases SET {', '.join(sets)} WHERE id = ?", params)


def delete_case(case_id):
    for t in ("messages", "competencies", "evidence", "decisions", "escalations"):
        db.execute(f"DELETE FROM {t} WHERE case_id = ?", [case_id])
    db.execute("DELETE FROM cases WHERE id = ?", [case_id])


def touch(case_id):
    db.execute("UPDATE cases SET updated_at = ? WHERE id = ?", [db.now_iso(), case_id])


# ---------------------------------------------------------------------------
# Messages / transcript
# ---------------------------------------------------------------------------
def add_message(case_id, role, content):
    db.insert(
        "INSERT INTO messages (case_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        [case_id, role, content, db.now_iso()])
    touch(case_id)


def get_messages(case_id, roles=None):
    rows = db.query(
        "SELECT * FROM messages WHERE case_id = ? ORDER BY id", [case_id])
    if roles:
        rows = [r for r in rows if r["role"] in roles]
    return rows


# ---------------------------------------------------------------------------
# Competencies & evidence reads
# ---------------------------------------------------------------------------
def get_competencies(case_id):
    return db.query(
        "SELECT * FROM competencies WHERE case_id = ? ORDER BY id", [case_id])


def get_evidence(case_id):
    return db.query(
        "SELECT id, case_id, filename, size_bytes, mime_type, storage_url, "
        "storage_kind, competency_id, mapping_status, ai_suggested_competency, "
        "created_at FROM evidence WHERE case_id = ? ORDER BY id", [case_id])


def get_evidence_row(evidence_id):
    """Full row including inline_data and extracted_text (for download/AI)."""
    return db.query_one("SELECT * FROM evidence WHERE id = ?", [evidence_id])


def add_evidence(case_id, filename, size_bytes, mime, stored, extracted_text):
    return db.insert(
        """INSERT INTO evidence
           (case_id, filename, size_bytes, mime_type, storage_url, storage_kind,
            inline_data, extracted_text, competency_id, mapping_status,
            ai_suggested_competency, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'unlinked', NULL, ?)""",
        [case_id, filename, size_bytes, mime, stored["storage_url"],
         stored["storage_kind"], stored.get("inline_data"), extracted_text,
         db.now_iso()])


def set_evidence_suggestion(evidence_id, competency_name):
    status = "needs_review" if competency_name else "unlinked"
    db.execute("UPDATE evidence SET ai_suggested_competency = ?, mapping_status = ? "
               "WHERE id = ?", [competency_name, status, evidence_id])


def link_evidence(evidence_id, competency_id):
    db.execute("UPDATE evidence SET competency_id = ?, mapping_status = 'mapped' "
               "WHERE id = ?", [competency_id, evidence_id])
    _sync_competency_status(competency_id)


def unlink_evidence(evidence_id):
    row = get_evidence_row(evidence_id)
    old_comp = row.get("competency_id") if row else None
    db.execute("UPDATE evidence SET competency_id = NULL, mapping_status = 'unlinked' "
               "WHERE id = ?", [evidence_id])
    if old_comp:
        _sync_competency_status(old_comp)


def delete_evidence(evidence_id):
    row = get_evidence_row(evidence_id)
    comp = row.get("competency_id") if row else None
    db.execute("DELETE FROM evidence WHERE id = ?", [evidence_id])
    if comp:
        _sync_competency_status(comp)


QUEUE_FILTERS = {
    "needs_review": [STATUS_SUBMITTED, STATUS_IN_REVIEW],
    "in_progress": [STATUS_DRAFT],
    "completed": [STATUS_APPROVED, STATUS_DENIED, STATUS_REVISION, STATUS_ESCALATED],
}


def list_review_cases(status_filter="all", q=""):
    rows = db.query("SELECT * FROM cases ORDER BY updated_at DESC")
    if status_filter and status_filter != "all":
        allowed = QUEUE_FILTERS.get(status_filter, [])
        rows = [r for r in rows if r.get("status") in allowed]
    q = (q or "").strip().lower()
    if q:
        rows = [r for r in rows if q in (
            f"{r.get('applicant_name','')} {r.get('case_code','')} "
            f"{r.get('target_course','')}").lower()]
    return rows


def queue_counts():
    rows = db.query("SELECT status FROM cases")
    counts = {"all": len(rows), "needs_review": 0, "in_progress": 0, "completed": 0}
    for r in rows:
        for key, statuses in QUEUE_FILTERS.items():
            if r.get("status") in statuses:
                counts[key] += 1
    return counts


def get_routing_rules():
    return db.query("SELECT * FROM routing_rules ORDER BY id")


def add_routing_rule(condition_type, condition_value, action_type, action_value):
    return db.insert(
        """INSERT INTO routing_rules
           (condition_type, condition_value, action_type, action_value, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        [condition_type, condition_value, action_type, action_value, db.now_iso()])


def delete_routing_rule(rule_id):
    db.execute("DELETE FROM routing_rules WHERE id = ?", [rule_id])


# --- catalog / knowledge base ---
def list_catalog():
    return db.query("SELECT * FROM catalog ORDER BY type, code")


def add_catalog(ctype, code, title, content):
    return db.insert(
        """INSERT INTO catalog (type, code, title, content, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [ctype, code, title, content, db.now_iso(), db.now_iso()])


def update_catalog(entry_id, fields):
    allowed = ["type", "code", "title", "content"]
    sets, params = [], []
    for k in allowed:
        if k in fields:
            sets.append(f"{k} = ?")
            params.append(fields[k])
    if not sets:
        return
    params.append(db.now_iso())
    params.append(entry_id)
    db.execute(f"UPDATE catalog SET {', '.join(sets)}, updated_at = ? WHERE id = ?", params)


def delete_catalog(entry_id):
    db.execute("DELETE FROM catalog WHERE id = ?", [entry_id])


def apply_routing_rules(case_id):
    """Evaluate routing rules against a case and set assignee/flags accordingly.

    condition_type: 'course_matches' (glob-ish prefix/contains) | 'confidence_below'
    action_type:    'assign' (assignee_name) | 'flag' (flag label)
    """
    case = get_case(case_id)
    if not case:
        return
    course = (case.get("target_course") or "").lower()
    conf = case.get("ai_confidence")
    assignee = case.get("assignee")
    flags = [f for f in (case.get("flags") or "").split(",") if f.strip()]

    for rule in get_routing_rules():
        ctype = rule.get("condition_type")
        cval = (rule.get("condition_value") or "").strip()
        matched = False
        if ctype == "course_matches" and cval:
            pat = cval.lower().rstrip("*")
            matched = course.startswith(pat) or (pat in course)
        elif ctype == "confidence_below" and cval:
            try:
                matched = conf is not None and conf < int(cval)
            except ValueError:
                matched = False
        if not matched:
            continue
        if rule.get("action_type") == "assign" and rule.get("action_value"):
            assignee = rule["action_value"]
        elif rule.get("action_type") == "flag" and rule.get("action_value"):
            if rule["action_value"] not in flags:
                flags.append(rule["action_value"])

    update_case(case_id, {"assignee": assignee, "flags": ",".join(flags)})


DECISION_STATUS = {
    "approve": STATUS_APPROVED,
    "deny": STATUS_DENIED,
    "revise": STATUS_REVISION,
}


def get_decisions(case_id):
    return db.query(
        "SELECT * FROM decisions WHERE case_id = ? ORDER BY id DESC", [case_id])


def get_escalations(case_id):
    return db.query(
        "SELECT * FROM escalations WHERE case_id = ? ORDER BY id DESC", [case_id])


def mark_in_review(case_id):
    case = get_case(case_id)
    if case and case["status"] == STATUS_SUBMITTED:
        update_case(case_id, {"status": STATUS_IN_REVIEW})


def record_decision(case_id, reviewer_id, decision, notes):
    db.insert(
        """INSERT INTO decisions (case_id, reviewer_id, decision, notes, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        [case_id, reviewer_id, decision, notes, db.now_iso()])
    update_case(case_id, {"status": DECISION_STATUS.get(decision, STATUS_IN_REVIEW)})


def record_escalation(case_id, etype, assignee_name, assignee_email, notes):
    db.insert(
        """INSERT INTO escalations
           (case_id, type, assignee_name, assignee_email, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [case_id, etype, assignee_name, assignee_email, notes, db.now_iso()])
    update_case(case_id, {"status": STATUS_ESCALATED})


def latest_feedback(case_id):
    """Most recent reviewer decision + notes, surfaced to the applicant."""
    rows = get_decisions(case_id)
    return rows[0] if rows else None


def _sync_competency_status(competency_id):
    """A competency is 'mapped' if any evidence links to it, else 'unlinked'."""
    if not competency_id:
        return
    row = db.query_one(
        "SELECT COUNT(*) AS c FROM evidence WHERE competency_id = ? AND mapping_status = 'mapped'",
        [competency_id])
    status = "mapped" if (row and row["c"] > 0) else "unlinked"
    db.execute("UPDATE competencies SET mapping_status = ? WHERE id = ?",
               [status, competency_id])


# ---------------------------------------------------------------------------
# Extraction merge (don't clobber applicant edits unless empty)
# ---------------------------------------------------------------------------
def merge_extraction(case_id, extraction):
    case = get_case(case_id)
    if not case:
        return
    updates = {}
    summary = (extraction.get("summary") or "").strip()
    if summary and not (case.get("summary") or "").strip():
        updates["summary"] = summary
    tc = extraction.get("target_course")
    if tc and not (case.get("target_course") or "").strip():
        updates["target_course"] = tc
    if updates:
        update_case(case_id, updates)

    # upsert competencies by name (case-insensitive)
    existing = {(c["name"] or "").strip().lower(): c for c in get_competencies(case_id)}
    for comp in extraction.get("competencies", []):
        name = (comp.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in existing:
            # refresh description if blank
            if not (existing[key].get("description") or "").strip() and comp.get("description"):
                db.execute("UPDATE competencies SET description = ? WHERE id = ?",
                           [comp.get("description"), existing[key]["id"]])
        else:
            db.insert(
                """INSERT INTO competencies
                   (case_id, name, description, mapping_status, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                [case_id, name, comp.get("description") or "", "unlinked", db.now_iso()])
    recompute_completion(case_id)


# ---------------------------------------------------------------------------
# Deterministic completion rubric (§3.6)
# ---------------------------------------------------------------------------
def recompute_completion(case_id):
    case = get_case(case_id)
    if not case:
        return 0
    comps = get_competencies(case_id)
    evidence = get_evidence(case_id)
    pct = 0

    # Identity provided (name + NU-ID): 10%
    if (case.get("applicant_name") or "").strip() and (case.get("applicant_nuid") or "").strip():
        pct += 10
    # Target course selected: 20%
    if (case.get("target_course") or "").strip():
        pct += 20
    # >= 1 claimed competency: 20%
    if comps:
        pct += 20
    # Every claimed competency has >= 1 mapped evidence: 30%
    if comps:
        mapped_comp_ids = {e.get("competency_id") for e in evidence
                           if e.get("competency_id") and e.get("mapping_status") == "mapped"}
        if all(c["id"] in mapped_comp_ids for c in comps):
            pct += 30
    # Summary present and >= N chars: 20%
    if len((case.get("summary") or "").strip()) >= SUMMARY_MIN_CHARS:
        pct += 20

    pct = max(0, min(100, pct))
    db.execute("UPDATE cases SET completion_pct = ?, updated_at = ? WHERE id = ?",
               [pct, db.now_iso(), case_id])
    return pct
