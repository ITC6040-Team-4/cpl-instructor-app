import os
from flask import Flask, render_template, request, jsonify, send_from_directory
from openai import AzureOpenAI

# Explicit template folder to avoid any ambiguity in App Service runtime
app = Flask(__name__, template_folder="templates")

def get_client():
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

    if not endpoint or not api_key:
        return None, "Missing AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_API_KEY"

    client = AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
    )
    return client, None

# ✅ Bulletproof static serving (works even with run-from-package / Oryx mounts)
@app.get("/static/<path:filename>")
def static_files(filename):
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    return send_from_directory(static_dir, filename)

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
    }
    return render_template("admin.html", status=status)

@app.get("/health")
def health():
    return jsonify({"status": "ok"})

@app.post("/api/chat")
def api_chat():
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

    try:
        resp = client.chat.completions.create(
            model=deployment,  # Azure deployment NAME (e.g., "gpt-4o")
            messages=[
                {"role": "system", "content": "You are a helpful instructor assistant for the CPL course."},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
        )

        answer = (resp.choices[0].message.content or "").strip()
        return jsonify({"answer": answer})

    except Exception as e:
        # Logs in App Service Log Stream (without exposing secrets)
        app.logger.exception("Azure OpenAI call failed")
        return jsonify({"error": f"Azure OpenAI call failed: {type(e).__name__}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
