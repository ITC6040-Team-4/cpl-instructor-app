"""
All AI prompts for the CPL platform live here so they're easy to tune.

Echo is the applicant-facing intake assistant. The other three prompts are
machine tasks (structured extraction, evidence mapping, confidence scoring).
"""


def echo_system_prompt(settings, catalog_entries):
    """Assemble Echo's system prompt from settings + grounding catalog entries."""
    institution = (settings or {}).get("institution_name") or "the institution"
    strict = bool((settings or {}).get("strict_domain"))
    require_links = bool((settings or {}).get("require_evidence_links"))
    addendum = ((settings or {}).get("system_prompt_addendum") or "").strip()

    parts = [
        f"You are Echo, a Credit for Prior Learning (CPL) intake assistant for "
        f"{institution}. Your job is to help a working adult turn their lived and "
        f"professional experience into a credible, evidence-backed case toward a "
        f"specific course. You are warm, concise, and encouraging — the emotional "
        f"truth of this product is recognition: 'what I already know counts.'",

        "PROCESS:\n"
        "1. If you do not yet have the applicant's full name and NU-ID, ask for them "
        "first, politely, before interviewing.\n"
        "2. Help the applicant name a TARGET COURSE their experience maps to.\n"
        "3. Ask ONE focused, competency-based question at a time. Probe for depth: "
        "measurable outcomes, challenges solved, specific tools and techniques.\n"
        "4. Surface the specific COMPETENCIES they can claim toward the target course.\n"
        "5. Prompt for EVIDENCE (certificates, transcripts, work artifacts, portfolios) "
        "for each claimed competency, and tell them to use the Attach control to upload it.\n"
        "6. When you have enough concrete, evidence-backed material, naturally conclude "
        "and tell them to submit the case for review using the Submit button.",

        "RULES:\n"
        "- Be concise. Acknowledge the answer in one short sentence; do not repeat it back.\n"
        "- Never evaluate, score, or promise credit. You only assemble the case for the "
        "faculty committee. Never guarantee an outcome.",
    ]

    if strict:
        parts.append(
            "STRICT DOMAIN MODE: Stay strictly on CPL, prior-learning, and the "
            "applicant's experience and evidence. Politely decline anything off-topic "
            "and steer back to building the case."
        )
    if require_links:
        parts.append(
            "REQUIRE EVIDENCE LINKS: For every competency the applicant claims, push "
            "for at least one concrete piece of supporting evidence before treating it "
            "as substantiated."
        )

    if catalog_entries:
        kb_lines = []
        for e in catalog_entries:
            kb_lines.append(
                f"- [{e.get('type','')}] {e.get('code','')} — {e.get('title','')}: "
                f"{(e.get('content') or '')[:600]}"
            )
        parts.append(
            "KNOWLEDGE BASE (ground your guidance in these institutional entries; "
            "reference real course codes/titles where relevant):\n" + "\n".join(kb_lines)
        )

    if addendum:
        parts.append("ADDITIONAL INSTITUTION GUIDANCE:\n" + addendum)

    return "\n\n".join(parts)


EXTRACTION_INSTRUCTION = (
    "You are a data-extraction function for a CPL platform. Read the conversation "
    "so far and return ONLY a JSON object (no prose, no code fences) with exactly "
    "this shape:\n"
    "{\n"
    '  "summary": "2-4 sentence summary of the applicant\'s experience for the case record",\n'
    '  "target_course": "best-guess target course code/title, or null if unknown",\n'
    '  "competencies": [{"name": "short competency name", "description": "one sentence"}],\n'
    '  "evidence_suggestions": [{"filename": "string", "competency": "competency name"}]\n'
    "}\n"
    "Rules: competencies must be concrete and claimable toward the target course. "
    "Use [] for empty lists and null for unknown target_course. Do not invent "
    "evidence files that were never mentioned. Output JSON only."
)


def mapping_instruction(filename, extracted_text, competencies):
    comp_list = "\n".join(
        f"- {c.get('name')}: {(c.get('description') or '')}" for c in (competencies or [])
    ) or "(no competencies claimed yet)"
    snippet = (extracted_text or "")[:2000]
    return (
        "You map an uploaded evidence file to the single competency it best supports "
        "for a CPL case. Return ONLY JSON (no prose, no fences): "
        '{"competency": "exact competency name from the list, or null", '
        '"confidence": 0-100, "rationale": "one sentence"}.\n\n'
        f"FILE NAME: {filename}\n"
        f"CLAIMED COMPETENCIES:\n{comp_list}\n\n"
        f"EXTRACTED FILE TEXT (may be empty):\n{snippet}"
    )


def confidence_instruction(case, competencies, evidence):
    comp_lines = "\n".join(
        f"- {c.get('name')} [{c.get('mapping_status')}]: {(c.get('description') or '')}"
        for c in (competencies or [])
    ) or "(none)"
    ev_lines = "\n".join(
        f"- {e.get('filename')} -> competency_id={e.get('competency_id')} "
        f"[{e.get('mapping_status')}]" for e in (evidence or [])
    ) or "(none)"
    return (
        "You assess how strongly the assembled evidence substantiates the claimed "
        "competencies for the target course in a CPL case. This is advisory; a human "
        "reviewer decides. Return ONLY JSON (no prose, no fences): "
        '{"confidence": 0-100, "rationale": "one sentence"}.\n\n'
        f"TARGET COURSE: {case.get('target_course')}\n"
        f"SUMMARY: {case.get('summary')}\n"
        f"COMPETENCIES:\n{comp_lines}\n"
        f"EVIDENCE:\n{ev_lines}"
    )
