"""
Data layer for the CPL evaluation platform.

Backend-aware: uses Azure SQL via pyodbc when SQL_CONNECTION_STRING is set
(production), and falls back to a local SQLite file for local dev/testing so
the app is runnable at every checkpoint. Both drivers use qmark ('?')
parameters, so application queries are written once and run on either backend.

Public surface:
    backend()                 -> "sqlserver" | "sqlite"
    get_conn()                -> a DB connection (caller closes, or use with-block)
    query(sql, params)        -> list[dict]
    query_one(sql, params)    -> dict | None
    execute(sql, params)      -> affected rowcount
    insert(sql, params)       -> new row id (dialect-safe)
    init_db()                 -> create tables if missing + seed defaults
    now_iso()                 -> ISO-8601 UTC timestamp string
"""

import os
import datetime
import threading

_LOCAL_SQLITE_PATH = os.path.join(os.path.dirname(__file__), "cpl_local.db")
_init_lock = threading.Lock()
_initialized = False


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------
def backend():
    """Return the active DB backend identifier."""
    override = (os.getenv("DB_BACKEND") or "").strip().lower()
    if override in ("sqlite", "sqlserver"):
        return override
    return "sqlserver" if os.getenv("SQL_CONNECTION_STRING") else "sqlite"


def now_iso():
    """UTC timestamp as a sortable ISO-8601 string (stored as text in both backends)."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------
def get_conn():
    if backend() == "sqlserver":
        import pyodbc
        conn = pyodbc.connect(os.getenv("SQL_CONNECTION_STRING"), timeout=15)
        return conn
    else:
        import sqlite3
        conn = sqlite3.connect(_LOCAL_SQLITE_PATH, timeout=15)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _columns(cursor):
    return [c[0] for c in cursor.description] if cursor.description else []


def query(sql, params=None):
    """Run a SELECT, return list of dicts."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        cols = _columns(cur)
        rows = cur.fetchall()
        return [dict(zip(cols, [_norm(v) for v in row])) for row in rows]
    finally:
        conn.close()


def query_one(sql, params=None):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=None):
    """Run an INSERT/UPDATE/DELETE, return affected rowcount."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        rc = cur.rowcount
        conn.commit()
        return rc
    finally:
        conn.close()


def insert(sql, params=None):
    """Run an INSERT and return the new row id (dialect-safe)."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if backend() == "sqlserver":
            cur.execute("SELECT CAST(SCOPE_IDENTITY() AS INT)")
            new_id = cur.fetchone()[0]
        else:
            new_id = cur.lastrowid
        conn.commit()
        return int(new_id)
    finally:
        conn.close()


def _norm(v):
    """Normalize driver-specific values into plain Python types."""
    # pyodbc returns Decimal for numeric, datetime for datetime; keep simple
    import decimal
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray)):
        return v
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    return v


# ---------------------------------------------------------------------------
# Schema (dialect-aware DDL)
# ---------------------------------------------------------------------------
def _ddl():
    """Return ordered list of (table_name, create_sql) for the active backend."""
    sqlserver = backend() == "sqlserver"

    # type aliases
    PK = "INT IDENTITY(1,1) PRIMARY KEY" if sqlserver else "INTEGER PRIMARY KEY AUTOINCREMENT"
    TXT = "NVARCHAR(MAX)" if sqlserver else "TEXT"
    S = (lambda n: f"NVARCHAR({n})") if sqlserver else (lambda n: "TEXT")
    INT = "INT"
    REAL = "FLOAT" if sqlserver else "REAL"
    TS = S(40)  # ISO-8601 timestamp text

    tables = [
        ("reviewers", f"""
            CREATE TABLE reviewers (
                id {PK},
                email {S(255)} NOT NULL UNIQUE,
                password_hash {S(255)} NOT NULL,
                name {S(255)},
                created_at {TS}
            )"""),
        ("settings", f"""
            CREATE TABLE settings (
                id {INT} PRIMARY KEY,
                institution_name {S(255)},
                draft_threshold {INT},
                submit_threshold {INT},
                delete_below_threshold {INT},
                strict_domain {INT},
                require_evidence_links {INT},
                system_prompt_addendum {TXT},
                updated_at {TS}
            )"""),
        ("cases", f"""
            CREATE TABLE cases (
                id {PK},
                case_code {S(40)} NOT NULL UNIQUE,
                applicant_name {S(255)},
                applicant_nuid {S(64)},
                target_course {S(255)},
                status {S(40)},
                completion_pct {INT},
                ai_confidence {INT},
                ai_confidence_rationale {TXT},
                summary {TXT},
                assignee {S(255)},
                flags {TXT},
                created_at {TS},
                updated_at {TS}
            )"""),
        ("messages", f"""
            CREATE TABLE messages (
                id {PK},
                case_id {INT} NOT NULL,
                role {S(20)},
                content {TXT},
                created_at {TS}
            )"""),
        ("competencies", f"""
            CREATE TABLE competencies (
                id {PK},
                case_id {INT} NOT NULL,
                name {S(255)},
                description {TXT},
                mapping_status {S(20)},
                created_at {TS}
            )"""),
        ("evidence", f"""
            CREATE TABLE evidence (
                id {PK},
                case_id {INT} NOT NULL,
                filename {S(512)},
                size_bytes {INT},
                mime_type {S(128)},
                storage_url {S(1024)},
                storage_kind {S(20)},
                inline_data {TXT},
                extracted_text {TXT},
                competency_id {INT},
                mapping_status {S(20)},
                ai_suggested_competency {S(255)},
                created_at {TS}
            )"""),
        ("decisions", f"""
            CREATE TABLE decisions (
                id {PK},
                case_id {INT} NOT NULL,
                reviewer_id {INT},
                decision {S(20)},
                notes {TXT},
                created_at {TS}
            )"""),
        ("escalations", f"""
            CREATE TABLE escalations (
                id {PK},
                case_id {INT} NOT NULL,
                type {S(64)},
                assignee_name {S(255)},
                assignee_email {S(255)},
                notes {TXT},
                created_at {TS}
            )"""),
        ("routing_rules", f"""
            CREATE TABLE routing_rules (
                id {PK},
                condition_type {S(64)},
                condition_value {S(255)},
                action_type {S(64)},
                action_value {S(255)},
                created_at {TS}
            )"""),
        ("catalog", f"""
            CREATE TABLE catalog (
                id {PK},
                type {S(20)},
                code {S(64)},
                title {S(512)},
                content {TXT},
                created_at {TS},
                updated_at {TS}
            )"""),
    ]
    return tables


def _table_exists(cur, name):
    if backend() == "sqlserver":
        cur.execute(
            "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = ?", [name]
        )
    else:
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", [name]
        )
    return cur.fetchone() is not None


# Columns added after the initial schema; ensured on every boot so redeploys
# against an existing database pick them up without a manual migration.
_ADDED_COLUMNS = [
    ("evidence", "inline_data"),
]


def _column_exists(cur, table, column):
    if backend() == "sqlserver":
        cur.execute(
            "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ? AND COLUMN_NAME = ?",
            [table, column])
        return cur.fetchone() is not None
    else:
        cur.execute(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in cur.fetchall())


def _ensure_columns(cur):
    TXT = "NVARCHAR(MAX)" if backend() == "sqlserver" else "TEXT"
    for table, column in _ADDED_COLUMNS:
        if not _column_exists(cur, table, column):
            cur.execute(f"ALTER TABLE {table} ADD {column} {TXT}")


def init_db():
    """Create tables if absent and seed defaults. Idempotent; safe on every boot."""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        conn = get_conn()
        try:
            cur = conn.cursor()
            for name, ddl in _ddl():
                if not _table_exists(cur, name):
                    cur.execute(ddl)
            _ensure_columns(cur)
            conn.commit()
        finally:
            conn.close()
        _seed_defaults()
        _initialized = True


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------
def _seed_defaults():
    # Settings (single row, id=1)
    if not query_one("SELECT id FROM settings WHERE id = 1"):
        execute(
            """INSERT INTO settings
               (id, institution_name, draft_threshold, submit_threshold,
                delete_below_threshold, strict_domain, require_evidence_links,
                system_prompt_addendum, updated_at)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ["Provenance", 25, 80, 50, 1, 1, "", now_iso()],
        )

    # Narrow, reversible data update: rename a pre-existing seeded institution
    # name to the new brand without touching any structural value.
    execute("UPDATE settings SET institution_name = 'Provenance' "
            "WHERE institution_name = 'NUPathway'")

    # Reference Library: a couple of courses + a policy + an example
    if not query_one("SELECT id FROM catalog"):
        seed_catalog = [
            ("course", "CS5001", "Intensive Foundations of Computer Science",
             "Introduces programming, problem decomposition, data abstraction, and "
             "fundamental algorithms. Skills: writing and debugging programs, "
             "designing functions and data structures, recursion, and testing."),
            ("course", "PM6010", "Project Management Foundations",
             "Covers project lifecycle, scope, scheduling, budgeting, risk, and "
             "stakeholder communication. Skills: planning a project, tracking "
             "budget and schedule, managing risk, and leading cross-functional teams."),
            ("policy", "PLA-POL-01", "Artifact Standards for Prior Learning",
             "Credit is granted only when documented artifacts (certificates, "
             "transcripts, work products, or validated portfolios) substantiate each "
             "claim against the target course's learning outcomes. "
             "Self-attestation alone is insufficient."),
            ("example", "EX-001", "Example: Budget Tracking claim",
             "A learner managing a $250k departmental budget provided a quarterly "
             "variance report and a forecasting spreadsheet. This was mapped to the "
             "'Track budget and schedule' claim in PM6010."),
        ]
        for t, code, title, content in seed_catalog:
            execute(
                """INSERT INTO catalog (type, code, title, content, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [t, code, title, content, now_iso(), now_iso()],
            )

    # Reviewer from env (idempotent)
    _seed_reviewer()


def _seed_reviewer():
    email = (os.getenv("SEED_REVIEWER_EMAIL") or "").strip().lower()
    password = os.getenv("SEED_REVIEWER_PASSWORD")
    if not email or not password:
        return
    if query_one("SELECT id FROM reviewers WHERE email = ?", [email]):
        return
    try:
        import bcrypt
        pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    except Exception:
        return
    name = os.getenv("SEED_REVIEWER_NAME") or email.split("@")[0].title()
    execute(
        "INSERT INTO reviewers (email, password_hash, name, created_at) VALUES (?, ?, ?, ?)",
        [email, pw_hash, name, now_iso()],
    )
