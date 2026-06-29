"""
Reviewer authentication: bcrypt password verification + Flask-session gating.

Reviewer/admin routes are protected server-side with @require_reviewer (not just
hidden in the UI). Sessions store only the reviewer id.
"""

import functools
from flask import session, jsonify

import db


def verify_login(email, password):
    """Return the reviewer row on success, else None."""
    email = (email or "").strip().lower()
    if not email or not password:
        return None
    row = db.query_one("SELECT * FROM reviewers WHERE email = ?", [email])
    if not row:
        return None
    try:
        import bcrypt
        if bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8")):
            return row
    except Exception:
        return None
    return None


def login_session(reviewer):
    session["reviewer_id"] = reviewer["id"]
    session["reviewer_name"] = reviewer.get("name") or reviewer["email"]


def logout_session():
    session.pop("reviewer_id", None)
    session.pop("reviewer_name", None)


def current_reviewer():
    rid = session.get("reviewer_id")
    if not rid:
        return None
    return db.query_one("SELECT id, email, name FROM reviewers WHERE id = ?", [rid])


def is_authenticated():
    return bool(session.get("reviewer_id"))


def require_reviewer(fn):
    """Decorator: 401 JSON for API routes, used by reviewer/admin endpoints."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_authenticated():
            return jsonify({"error": "Authentication required"}), 401
        return fn(*args, **kwargs)
    return wrapper
