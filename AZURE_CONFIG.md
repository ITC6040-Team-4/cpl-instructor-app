# Azure configuration

Every setting the app reads, and where to put it. In Azure, set these under
**App Service → Configuration → Application settings** (each is an environment
variable). Never commit secrets — the app reads everything from the environment.

## Existing settings (already in use — keep them)

| Setting | Required | Purpose |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | Yes | Azure OpenAI resource endpoint URL |
| `AZURE_OPENAI_API_KEY` | Yes | Azure OpenAI API key |
| `AZURE_OPENAI_API_VERSION` | No | Defaults to `2024-12-01-preview` |
| `AZURE_OPENAI_DEPLOYMENT` | Yes | Chat deployment/model name |
| `SQL_CONNECTION_STRING` | Yes (prod) | Azure SQL ODBC connection string. If unset, the app falls back to a local SQLite file (`cpl_local.db`) — fine for local dev, not for production. |
| `FLASK_SECRET_KEY` | Recommended | Signs the session cookie. Set a strong random value in production. |
| `MAX_CHAT_REQUESTS` | No | Caps Vera chat completions per worker process. `0`/unset = unlimited. Shown live in `/admin`. |

## New settings added by the CPL platform

| Setting | Required | Purpose |
|---|---|---|
| `AZURE_STORAGE_CONNECTION_STRING` | Recommended | Azure Blob Storage connection string for artifact files. **If unset**, the app stores files **under 1MB** inline (base64) in the DB and **rejects larger uploads** with a clear message — set this to accept files up to 50MB. |
| `AZURE_STORAGE_CONTAINER` | No | Blob container name. Defaults to `cpl-evidence` (auto-created). |
| `SEED_REVIEWER_EMAIL` | Yes (first run) | Seeds the initial assessor (faculty) login on startup. |
| `SEED_REVIEWER_PASSWORD` | Yes (first run) | Initial assessor password. Stored **bcrypt-hashed**, never in plaintext. Change it after first login (or rotate the seed values). |
| `SEED_REVIEWER_NAME` | No | Display name for the seeded assessor. Defaults from the email. |
| `DB_BACKEND` | No | Force `sqlite` or `sqlserver`. Normally inferred from `SQL_CONNECTION_STRING`. |

## Notes
- The seeded assessor is created only if no account with that email exists, so
  it's safe to leave set across redeploys.
- `MAX_CONTENT_LENGTH` is fixed at 55MB in code so oversized uploads are rejected
  before buffering.
- Database tables are created and seeded automatically on startup (idempotent).
  New columns added in later versions are applied on boot without a manual
  migration.
