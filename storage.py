"""
Evidence storage adapter.

Primary backend: Azure Blob Storage (AZURE_STORAGE_CONNECTION_STRING).
Fallback: store small files (< ~1MB) inline as base64 in the DB; reject larger
files with a clear message telling the user to configure blob storage.

Adapter surface (storage-backend agnostic for the rest of the app):
    save(case_id, filename, data, mime) -> {"storage_url", "storage_kind", "inline_data"}
    get_bytes(evidence_row)             -> bytes
    delete(evidence_row)                -> None

Also exposes extract_text(filename, data, mime) for PDF/DOCX/text.
"""

import os
import io
import base64
import logging

log = logging.getLogger(__name__)

MAX_FILE_BYTES = 50 * 1024 * 1024          # 50 MB hard cap
INLINE_FALLBACK_MAX = 1 * 1024 * 1024      # 1 MB when no blob storage configured
CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER", "cpl-evidence")

ALLOWED_EXT = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _conn_str():
    return os.getenv("AZURE_STORAGE_CONNECTION_STRING")


def blob_enabled():
    return bool(_conn_str())


def validate(filename, size_bytes):
    """Return (ok, error_message)."""
    ext = os.path.splitext((filename or "").lower())[1]
    if ext not in ALLOWED_EXT:
        return False, f"Unsupported file type '{ext or filename}'. Accepted: PDF, DOCX, images."
    if size_bytes > MAX_FILE_BYTES:
        return False, "File exceeds the 50MB limit."
    if not blob_enabled() and size_bytes > INLINE_FALLBACK_MAX:
        return False, ("Files over 1MB require blob storage. Ask an admin to set "
                       "AZURE_STORAGE_CONNECTION_STRING in the app configuration.")
    return True, None


# ---------------------------------------------------------------------------
# Save / fetch / delete
# ---------------------------------------------------------------------------
def _blob_client():
    from azure.storage.blob import BlobServiceClient
    svc = BlobServiceClient.from_connection_string(_conn_str())
    try:
        svc.create_container(CONTAINER)
    except Exception:
        pass  # already exists
    return svc


def save(case_id, filename, data, mime):
    if blob_enabled():
        import uuid
        blob_name = f"case-{case_id}/{uuid.uuid4().hex}-{os.path.basename(filename)}"
        svc = _blob_client()
        client = svc.get_blob_client(container=CONTAINER, blob=blob_name)
        client.upload_blob(data, overwrite=True)
        return {"storage_url": blob_name, "storage_kind": "blob", "inline_data": None}
    else:
        log.warning("AZURE_STORAGE_CONNECTION_STRING not set — storing evidence inline (base64).")
        return {
            "storage_url": f"inline://{os.path.basename(filename)}",
            "storage_kind": "inline",
            "inline_data": base64.b64encode(data).decode("ascii"),
        }


def get_bytes(evidence_row):
    kind = evidence_row.get("storage_kind")
    if kind == "blob":
        svc = _blob_client()
        client = svc.get_blob_client(container=CONTAINER, blob=evidence_row["storage_url"])
        return client.download_blob().readall()
    elif kind == "inline":
        return base64.b64decode(evidence_row.get("inline_data") or "")
    return b""


def delete(evidence_row):
    if evidence_row.get("storage_kind") == "blob":
        try:
            svc = _blob_client()
            client = svc.get_blob_client(container=CONTAINER, blob=evidence_row["storage_url"])
            client.delete_blob()
        except Exception:
            log.exception("blob delete failed (continuing)")
    # inline rows need no external cleanup


# ---------------------------------------------------------------------------
# Text extraction (best-effort)
# ---------------------------------------------------------------------------
def extract_text(filename, data, mime=None):
    name = (filename or "").lower()
    try:
        if name.endswith(".pdf"):
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages).strip()
        if name.endswith(".docx"):
            import docx
            doc = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs).strip()
        if name.endswith((".txt", ".csv", ".md")):
            return data.decode("utf-8", errors="replace").strip()
    except Exception:
        log.exception("text extraction failed for %s", filename)
    return ""
