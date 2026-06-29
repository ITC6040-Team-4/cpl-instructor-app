# CPL Evaluation Platform (Team 4)

A two-persona **Credit for Prior Learning** platform called **Provenance**. Learners
chat with **Vera**, an AI intake guide, to assemble an artifact-backed *portfolio*
toward a course; faculty **assessors** triage a docket, read the portfolio, and
render a decision.

Built on the original Flask + Azure OpenAI + Azure SQL stack (no framework rewrite).

## What it does

- **Learner** — portfolio chat with Vera, a live **Chain of Evidence** (claims
  as slots, artifact cards linked into them), structured extraction into the
  Portfolio Builder, artifact upload (PDF/DOCX/images, 50MB) with AI claim-mapping
  suggestions, a transparent Progress rubric, threshold-gated submit, and a
  portfolio history with assessor feedback.
- **Assessor** (login-gated) — a sortable, searchable **Docket** with filter
  tabs, Provenance Score dials, and CSV export; a full **portfolio review** with a
  read-only Intake Record audit log, artifacts + mappings, and a decision action bar
  (Approve / Deny / Request Revision / Escalate).
- **Admin/Settings** (assessor-gated) — institution name + thresholds, AI
  guardrails (Focused Mode, Require Artifact Links, Guidance Note),
  workflow **routing rules** (applied on submit), and a **course catalog / KB**
  that grounds Vera.
- **Shell** — ⌘K command palette, role switcher, live queue badge, system links.

## Architecture

| File | Responsibility |
|---|---|
| `app.py` | Flask routes (learner, assessor, system) + error handling |
| `db.py` | Backend-aware data layer (Azure SQL via pyodbc / SQLite dev fallback), idempotent migrations + seed |
| `services.py` | Portfolio lifecycle, deterministic Progress rubric, extraction merge, routing rules, docket |
| `ai.py` | Azure OpenAI: Vera chat, JSON extraction, mapping, Provenance Score; `MAX_CHAT_REQUESTS` counter |
| `prompts.py` | All AI prompts (one place to tune) |
| `storage.py` | Artifact storage adapter (Azure Blob / inline fallback) + PDF/DOCX text extraction |
| `auth.py` | Assessor bcrypt auth + session gating |
| `templates/`, `static/` | Jinja templates + the "Patina" design system, Chain of Evidence, command palette |

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
artifacts under 1MB are stored inline. With no Azure OpenAI vars, pages still load
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
