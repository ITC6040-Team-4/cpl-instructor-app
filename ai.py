"""
Azure OpenAI integration for the CPL platform.

Reuses the existing deployment/config. Four jobs:
  1. chat()          - Echo intake conversation
  2. extract_case()  - structured extraction into the case record (JSON)
  3. suggest_mapping() - map an evidence file to a competency (JSON)
  4. score_confidence() - advisory 0-100 confidence on submit (JSON)

Also owns the MAX_CHAT_REQUESTS rate-limit counter surfaced in /admin.
"""

import os
import json
import threading

from openai import AzureOpenAI
import prompts

# ---------------------------------------------------------------------------
# Rate-limit counter (in-process; resets on worker restart)
# ---------------------------------------------------------------------------
_counter_lock = threading.Lock()
_current_requests = 0


def max_chat_requests():
    try:
        return int(os.getenv("MAX_CHAT_REQUESTS", "0"))
    except (TypeError, ValueError):
        return 0


def current_chat_requests():
    return _current_requests


def _reserve_request():
    """Increment the counter if under the cap. Returns (ok, message)."""
    global _current_requests
    cap = max_chat_requests()
    with _counter_lock:
        if cap > 0 and _current_requests >= cap:
            return False, f"Chat request limit reached ({cap}). Please try again later."
        _current_requests += 1
        return True, None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
def get_client():
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    if not endpoint:
        return None, "Missing AZURE_OPENAI_ENDPOINT"
    if not api_key:
        return None, "Missing AZURE_OPENAI_API_KEY"
    try:
        return AzureOpenAI(azure_endpoint=endpoint, api_key=api_key,
                           api_version=api_version), None
    except Exception as e:
        return None, f"Client initialization failed: {type(e).__name__}"


def _deployment():
    return os.getenv("AZURE_OPENAI_DEPLOYMENT")


def _completion(messages, temperature=0.3, json_mode=False, count=True):
    """Low-level completion. Returns (text, error)."""
    if count:
        ok, msg = _reserve_request()
        if not ok:
            return None, msg
    deployment = _deployment()
    if not deployment:
        return None, "Missing AZURE_OPENAI_DEPLOYMENT"
    client, err = get_client()
    if err:
        return None, err
    try:
        kwargs = {"model": deployment, "messages": messages, "temperature": temperature}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip(), None
    except Exception as e:
        # Retry once without json_mode in case the deployment rejects response_format
        if json_mode:
            try:
                resp = client.chat.completions.create(
                    model=deployment, messages=messages, temperature=temperature)
                return (resp.choices[0].message.content or "").strip(), None
            except Exception:
                pass
        return None, f"Azure OpenAI call failed: {type(e).__name__}"


# ---------------------------------------------------------------------------
# Job 1: Echo chat
# ---------------------------------------------------------------------------
def chat(history, settings, catalog_entries):
    """history: list of {role, content} (user/assistant). Returns (answer, error)."""
    system = {"role": "system", "content": prompts.echo_system_prompt(settings, catalog_entries)}
    messages = [system] + [
        {"role": m["role"], "content": m["content"]}
        for m in history if m.get("role") in ("user", "assistant")
    ]
    return _completion(messages, temperature=0.3)


# ---------------------------------------------------------------------------
# JSON parsing helper (defensive)
# ---------------------------------------------------------------------------
def _parse_json(text):
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        # strip code fences
        t = t.split("```", 2)
        t = t[1] if len(t) > 1 else text
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    # find first { and last }
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start:end + 1]
    try:
        return json.loads(t)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Job 2: structured extraction
# ---------------------------------------------------------------------------
def extract_case(history):
    convo = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in history
        if m.get("role") in ("user", "assistant")
    )
    messages = [
        {"role": "system", "content": prompts.EXTRACTION_INSTRUCTION},
        {"role": "user", "content": "CONVERSATION:\n" + convo},
    ]
    text, err = _completion(messages, temperature=0.1, json_mode=True, count=False)
    if err:
        return None, err
    data = _parse_json(text)
    if not isinstance(data, dict):
        return None, "Extraction returned malformed JSON"
    # normalize
    data.setdefault("summary", "")
    tc = data.get("target_course")
    data["target_course"] = None if tc in ("", "null", None) else tc
    if not isinstance(data.get("competencies"), list):
        data["competencies"] = []
    if not isinstance(data.get("evidence_suggestions"), list):
        data["evidence_suggestions"] = []
    return data, None


# ---------------------------------------------------------------------------
# Job 3: evidence mapping suggestion
# ---------------------------------------------------------------------------
def suggest_mapping(filename, extracted_text, competencies):
    messages = [
        {"role": "system", "content": "You return only JSON."},
        {"role": "user",
         "content": prompts.mapping_instruction(filename, extracted_text, competencies)},
    ]
    text, err = _completion(messages, temperature=0.1, json_mode=True, count=False)
    if err:
        return None, err
    data = _parse_json(text)
    if not isinstance(data, dict):
        return None, "Mapping returned malformed JSON"
    return data, None


# ---------------------------------------------------------------------------
# Job 4: confidence scoring (on submit)
# ---------------------------------------------------------------------------
def score_confidence(case, competencies, evidence):
    messages = [
        {"role": "system", "content": "You return only JSON."},
        {"role": "user",
         "content": prompts.confidence_instruction(case, competencies, evidence)},
    ]
    text, err = _completion(messages, temperature=0.1, json_mode=True, count=False)
    if err:
        return None, err
    data = _parse_json(text)
    if not isinstance(data, dict):
        return None, "Confidence scoring returned malformed JSON"
    try:
        conf = int(round(float(data.get("confidence", 0))))
    except (TypeError, ValueError):
        conf = 0
    return {"confidence": max(0, min(100, conf)),
            "rationale": (data.get("rationale") or "").strip()}, None
