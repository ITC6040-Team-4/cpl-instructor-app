import os
from flask import Flask, render_template, request, jsonify, send_from_directory, session
from openai import AzureOpenAI
import uuid

# NEW: DB test imports
import pyodbc


# Explicit template folder for Azure App Service reliability
app = Flask(__name__, template_folder="templates")

app.secret_key = os.getenv("FLASK_SECRET_KEY", "cpl-dev-secret-key-2026") # Required to use Flask sessions
chat_memory = {}

# ===============================
# Azure OpenAI Client Factory
# ===============================
def get_client():
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

    if not endpoint:
        return None, "Missing AZURE_OPENAI_ENDPOINT"
    if not api_key:
        return None, "Missing AZURE_OPENAI_API_KEY"

    try:
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        return client, None
    except Exception as e:
        return None, f"Client initialization failed: {type(e).__name__}"


# ===============================
# Static File Route (bulletproof)
# ===============================
@app.get("/static/<path:filename>")
def static_files(filename):
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    return send_from_directory(static_dir, filename)


# ===============================
# Basic Pages
# ===============================
@app.get("/")
def home():
    return render_template("index.html")


@app.get("/chat")
def chat_page():
    return render_template("chat.html")


@app.get("/admin")
def admin_page():
    status = {
        "AZURE_OPENAI_ENDPOINT": "✅ set" if os.getenv("AZURE_OPENAI_ENDPOINT") else "❌ missing",
        "AZURE_OPENAI_API_KEY": "✅ set" if os.getenv("AZURE_OPENAI_API_KEY") else "❌ missing",
        "AZURE_OPENAI_API_VERSION": os.getenv("AZURE_OPENAI_API_VERSION") or "(default: 2024-12-01-preview)",
        "AZURE_OPENAI_DEPLOYMENT": "✅ set" if os.getenv("AZURE_OPENAI_DEPLOYMENT") else "❌ missing",
        # NEW: show whether SQL conn string is present (but never show its value)
        "SQL_CONNECTION_STRING": "✅ set" if os.getenv("SQL_CONNECTION_STRING") else "❌ missing",
    }
    return render_template("admin.html", status=status)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


# ===============================
# 🔍 DEBUG SUPERPOWER ROUTE
# Shows SDK versions for troubleshooting
# ===============================
@app.get("/versions")
def versions():
    try:
        import openai
        import httpx
        return jsonify({
            "openai_version": getattr(openai, "__version__", "unknown"),
            "httpx_version": getattr(httpx, "__version__", "unknown"),
            "python_version": os.sys.version,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===============================
# ✅ DB CHECK ROUTE
# Verifies Web App can connect to Azure SQL
# ===============================
@app.get("/dbcheck")
def dbcheck():
    conn_str = os.getenv("SQL_CONNECTION_STRING")
    if not conn_str:
        return jsonify({"error": "Missing SQL_CONNECTION_STRING"}), 500

    try:
        # Keep it simple: open connection and run a tiny query
        conn = pyodbc.connect(conn_str, timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        row = cursor.fetchone()
        conn.close()

        return jsonify({"status": "DB Connected", "result": int(row[0])})
    except Exception as e:
        # Log full traceback in Azure Log Stream
        app.logger.exception("DB connection check failed")
        return jsonify({
            "error": f"DB check failed: {type(e).__name__}",
            "details": str(e),
        }), 500


# ===============================
# Chat API Endpoint
# ===============================
@app.post("/api/chat")
def api_chat():
    try:
        data = request.get_json(silent=True) or {}
        user_message = (data.get("message") or "").strip()

        if not user_message:
            return jsonify({"error": "Message is required"}), 400

        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        if not deployment:
            return jsonify({"error": "Missing AZURE_OPENAI_DEPLOYMENT"}), 500

        client, err = get_client()
        if err:
            return jsonify({"error": err}), 500

        # --- 1. SESSION MANAGEMENT ---
        if "session_id" not in session:
            session["session_id"] = str(uuid.uuid4())
        
        sid = session["session_id"]

        # --- 2. INITIALIZE CPL PERSONA IF NEW SESSION ---
        if sid not in chat_memory:
            chat_memory[sid] = [
                {
                    "role": "system", 
                    "content": (
                        "You are an academic Evaluator Assistant for a Credit for Prior Learning (CPL) program. "
                        "Your goal is to conduct a structured, competency-based interview to help the student articulate their prior learning. "
                        "Ask exactly ONE question at a time. Wait for the user's response before asking the next question. "
                        "Do NOT evaluate, score, or grant credit. Simply gather detailed evidence regarding their professional experience."
                    )
                }
            ]

        # --- 3. APPEND USER MESSAGE TO HISTORY ---
        chat_memory[sid].append({"role": "user", "content": user_message})

        # --- 4. SEND ENTIRE HISTORY TO AZURE ---
        response = client.chat.completions.create(
            model=deployment,
            messages=chat_memory[sid],
            temperature=0.3,
        )

        answer = (response.choices[0].message.content or "").strip()

        # --- 5. APPEND AI ANSWER TO HISTORY ---
        chat_memory[sid].append({"role": "assistant", "content": answer})

        return jsonify({"answer": answer})

    except Exception as e:
        app.logger.exception("Azure OpenAI call failed")
        return jsonify({
            "error": f"Azure OpenAI call failed: {type(e).__name__}"
        }), 500


# ===============================
# Local Dev Entry Point
# ===============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
