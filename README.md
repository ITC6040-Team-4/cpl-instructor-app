# CPL Evaluation Platform (Team 4)

A two-persona **Credit for Prior Learning** platform. Applicants chat with **Echo**,
an AI intake assistant, to assemble an evidence-backed *case* toward a course;
faculty **reviewers** triage a queue, read the case, and render a decision.

Built on the original Flask + Azure OpenAI + Azure SQL stack (no framework rewrite).

## What it does

- **Applicant** — case-bound chat with Echo, a live **Competency Map** (competencies
  as slots, evidence cards linked into them), structured extraction into the case
  record, evidence upload (PDF/DOCX/images, 50MB) with AI competency-mapping
  suggestions, a transparent completion rubric, threshold-gated submit, and a
  Case History with reviewer feedback.
- **Reviewer** (login-gated) — a sortable, searchable **Case Queue** with filter
  tabs, AI-confidence dials, and CSV export; a full **case review** with a
  read-only transcript audit log, evidence + mappings, and a decision action bar
  (Approve / Deny / Request Revision / Escalate).
- **Admin/Settings** (reviewer-gated) — institution name + thresholds, AI
  guardrails (strict-domain, require-evidence-links, system-prompt addendum),
  workflow **routing rules** (applied on submit), and a **course catalog / KB**
  that grounds Echo.
- **Shell** — ⌘K command palette, role switcher, live queue badge, system links.

## Architecture

| File | Responsibility |
|---|---|
| `app.py` | Flask routes (applicant, reviewer, system) + error handling |
| `db.py` | Backend-aware data layer (Azure SQL via pyodbc / SQLite dev fallback), idempotent migrations + seed |
| `services.py` | Case lifecycle, deterministic completion rubric, extraction merge, routing rules, queue |
| `ai.py` | Azure OpenAI: Echo chat, JSON extraction, mapping, confidence; `MAX_CHAT_REQUESTS` counter |
| `prompts.py` | All AI prompts (one place to tune) |
| `storage.py` | Evidence storage adapter (Azure Blob / inline fallback) + PDF/DOCX text extraction |
| `auth.py` | Reviewer bcrypt auth + session gating |
| `templates/`, `static/` | Jinja templates + the "Patina" design system, Competency Map, command palette |

System endpoints: `/health`, `/dbcheck` (returns `{result, status, backend}`),
`/admin` (config status + chat-request counter).

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # pyodbc needs system ODBC libs; skip it locally if absent
export SEED_REVIEWER_EMAIL=you@example.edu
export SEED_REVIEWER_PASSWORD=changeme
flask --app app run --port 8000
```

With no `SQL_CONNECTION_STRING`, the app uses a local SQLite file (`cpl_local.db`)
and creates/seeds the schema on first boot. With no `AZURE_STORAGE_CONNECTION_STRING`,
evidence under 1MB is stored inline. With no Azure OpenAI vars, pages still load
but chat/extraction return a clear error. Visit `/` to start.

> `pyodbc` is only imported when an Azure SQL connection string is present, so a
> local machine without ODBC drivers can still run the SQLite path.

## How it deploys

Pushing to `main` triggers `.github/workflows/main_cpl-instructor-app-prod.yml`,
which builds and deploys to Azure App Service (gunicorn via `startup.sh`). The
database schema and seed data are created automatically on startup.

## Configuration

All settings (existing + new) are documented in **[AZURE_CONFIG.md](AZURE_CONFIG.md)**.
Set them under App Service → Configuration. At minimum for production: the four
Azure OpenAI vars, `SQL_CONNECTION_STRING`, `FLASK_SECRET_KEY`,
`AZURE_STORAGE_CONNECTION_STRING`, and the `SEED_REVIEWER_*` pair.
