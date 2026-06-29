import os
from flask import Flask, render_template, request, jsonify, send_from_directory, session
from openai import AzureOpenAI
import uuid
import PyPDF2
import io
import smtplib
from email.message import EmailMessage

# Persistence layer (Azure SQL via pyodbc in prod, SQLite fallback for local dev)
import db
import services
import ai


# Explicit template folder for Azure App Service reliability
app = Flask(__name__, template_folder="templates")

app.secret_key = os.getenv("FLASK_SECRET_KEY", "cpl-dev-secret-key-2026") # Required to use Flask sessions
chat_memory = {}

# Initialize the database schema + seed on startup. Guarded so a transient DB
# outage degrades gracefully (routes that need the DB will surface their own
# errors) rather than crashing the whole worker on boot.
try:
    db.init_db()
    app.logger.info("Database initialized (backend=%s)", db.backend())
except Exception:
    app.logger.exception("Database initialization failed at startup")

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
    try:
        row = db.query_one("SELECT 1 AS result")
        return jsonify({
            "status": "DB Connected",
            "result": int(row["result"]),
            "backend": db.backend(),
        })
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
        # 1. SWITCH TO FORM DATA PARSING
        user_message = (request.form.get("message") or "").strip()
        uploaded_file = request.files.get("file")

        if not user_message and not uploaded_file:
            return jsonify({"error": "Message or file is required"}), 400

        # 2. EXTRACT TEXT FROM THE FILE
        file_text = ""
        if uploaded_file:
            filename = uploaded_file.filename.lower()
            file_bytes = uploaded_file.read()
            
            try:
                if filename.endswith(('.txt', '.csv', '.md')):
                    file_text = file_bytes.decode('utf-8')
                elif filename.endswith('.pdf'):
                    pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
                    for page in pdf_reader.pages:
                        file_text += (page.extract_text() or "") + "\n"
                else:
                    return jsonify({"error": "Unsupported file type. Please upload PDF or Text files."}), 400
            except Exception as e:
                return jsonify({"error": f"Failed to read file: {str(e)}"}), 400

        # 3. BUNDLE FILE CONTENT WITH USER MESSAGE
        final_prompt = user_message
        if file_text:
            final_prompt = f"[The user attached a document named '{uploaded_file.filename}']\n\nDOCUMENT CONTENT:\n{file_text}\n\nUSER MESSAGE:\n{user_message or 'Please review the attached document.'}"

        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        if not deployment:
            return jsonify({"error": "Missing AZURE_OPENAI_DEPLOYMENT"}), 500

        client, err = get_client()
        if err:
            return jsonify({"error": err}), 500

        if "session_id" not in session:
            session["session_id"] = str(uuid.uuid4())
        
        sid = session["session_id"]

        if sid not in chat_memory:
            chat_memory[sid] = [
                {
                    "role": "system", 
                    "content": (
                        "You are a master academic Evaluator Assistant for Northeastern University's Credit for Prior Learning (CPL) program. "
                        "You evaluate students for ALL colleges across Northeastern University.\n\n"
                        
                        "YOUR FIRST TASK:\n"
                        "You MUST begin the conversation by politely asking the student for their Full Name and Northeastern Student ID. Do not ask any interview questions until you have this information.\n\n"

                        "YOUR INTERVIEW KNOWLEDGE BASE:\n"
                        "Rely on your extensive pre-trained knowledge of standard university curricula. "
                        "When a student describes their professional background, dynamically identify specific Northeastern courses that align with their skills.\n\n"
                        
                        "CRITICAL RULES YOU MUST STRICTLY FOLLOW:\n"
                        "- BE EXTREMELY CONCISE. Acknowledge the user's answer in a single short sentence. Do NOT summarize or repeat their previous answers back to them.\n"
                        "- MEANINGFUL FOLLOW-UP QUESTIONS: Ask EXACTLY ONE short, competency-based interview question at a time. Analyze the user's previous answer and ask highly specific follow-ups to probe the depth of their competency. Explicitly ask about 'measurable outcomes', 'challenges you solved', or specific 'tools and techniques used'.\n"
                        "- Always wait for the user to answer before moving to the next question.\n"
                        "- PROACTIVE EVIDENCE & ARTIFACT GATHERING: You must explicitly reference 'documentation or artifacts' that could support the student's claims. If they mention a certification, degree, or tangible project, proactively ask them to upload corroborating proof (e.g., certificates, transcripts, or architecture diagrams) using the 'Attach' button.\n"
                        "- POLICY SAFETY (NO GUARANTEES): Do NOT evaluate, score, or promise credit. Never guarantee outcomes. State clearly that you are only gathering evidence for the appropriate faculty committee.\n"
                        "- If the user uploads a document, extract relevant evidence to map to potential outcomes.\n"
                        "- THE DYNAMIC STOPPING CONDITION: Continuously evaluate the depth of the student's responses and uploaded artifacts. Once you confidently deduce that you have gathered enough concrete proof to map their skills to relevant Northeastern course outcomes, NATURALLY CONCLUDE the interview. Do not drag it out. Thank the student briefly and explicitly instruct them to click the 'Submit to Advisor' button below the chat to send their official transcript for faculty review."
                    )
                }
            ]

        # Use the final_prompt which contains the bundled file text
        chat_memory[sid].append({"role": "user", "content": final_prompt})

        response = client.chat.completions.create(
            model=deployment,
            messages=chat_memory[sid],
            temperature=0.3,
        )

        answer = (response.choices[0].message.content or "").strip()
        chat_memory[sid].append({"role": "assistant", "content": answer})

        return jsonify({"answer": answer})

    except Exception as e:
        app.logger.exception("Azure OpenAI call failed")
        return jsonify({"error": f"Azure OpenAI call failed: {type(e).__name__}"}), 500

# ===============================
# Finalize & Email Route
# ===============================
@app.post("/api/submit")
def submit_application():
    try:
        if "session_id" not in session or session["session_id"] not in chat_memory:
            return jsonify({"error": "No active chat history found to submit."}), 400
        
        sid = session["session_id"]
        history = chat_memory[sid]

        client, err = get_client()
        if err: return jsonify({"error": err}), 500
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

        # 1. Ask the AI to summarize the entire chat history into an email body
        summary_prompt = list(history) # Copy the history
        summary_prompt.append({
            "role": "user", 
            "content": "The interview is over. Please read our entire conversation above and generate a formal email to the CPL Faculty Advisor. Extract the student's Name and Student ID. Summarize the evidence they provided, the documents they uploaded, and the specific academic areas their experience maps to. Do NOT include pleasantries like 'Sure, here is the email', just output the raw email text."
        })

        response = client.chat.completions.create(
            model=deployment,
            messages=summary_prompt,
            temperature=0.2,
        )
        email_body = response.choices[0].message.content.strip()

        # 2. Send the Email using Python's smtplib
        advisor_email = os.getenv("ADVISOR_EMAIL", "your-email@gmail.com") # Where the email goes
        bot_email = os.getenv("BOT_EMAIL") # The bot's email address
        bot_password = os.getenv("BOT_EMAIL_PASSWORD") # App password

        if not bot_email or not bot_password:
            # If you haven't set up the email keys yet, just print it to the terminal for testing
            print("\n--- SIMULATED EMAIL TO ADVISOR ---")
            print(email_body)
            print("----------------------------------\n")
            return jsonify({"status": "Simulation successful. Check server logs for email text.", "summary": email_body})

        # Actual email sending logic (Requires Gmail App Password in .env)
        msg = EmailMessage()
        msg.set_content(email_body)
        msg['Subject'] = "New CPL Application Ready for Review"
        msg['From'] = bot_email
        msg['To'] = advisor_email

        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(bot_email, bot_password)
        server.send_message(msg)
        server.quit()

        return jsonify({"status": "Email successfully sent to the advisor!"})

    except Exception as e:
        app.logger.exception("Failed to submit application")
        return jsonify({"error": str(e)}), 500

# ===============================
# Case-bound Applicant API (Phase 2)
# ===============================
def _case_record(case_id):
    """Full bundle for the applicant Case Record panel."""
    case = services.get_case(case_id)
    if not case:
        return None
    return {
        "case": case,
        "competencies": services.get_competencies(case_id),
        "evidence": services.get_evidence(case_id),
    }


@app.post("/api/cases")
def create_case():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    nuid = (data.get("nuid") or "").strip()
    if not name or not nuid:
        return jsonify({"error": "Name and NU-ID are required."}), 400
    try:
        case = services.create_case(name, nuid)
        session["case_id"] = case["id"]
        # Seed a system message so the transcript has provenance.
        services.add_message(case["id"], "system",
                             f"Case opened by {name} (NU-ID {nuid}).")
        return jsonify(_case_record(case["id"]))
    except Exception:
        app.logger.exception("create_case failed")
        return jsonify({"error": "Could not create case."}), 500


@app.get("/api/cases")
def list_cases():
    nuid = (request.args.get("nuid") or "").strip()
    if not nuid:
        return jsonify({"error": "nuid is required"}), 400
    return jsonify({"cases": services.list_cases_by_nuid(nuid)})


@app.get("/api/cases/<int:case_id>")
def get_case_api(case_id):
    rec = _case_record(case_id)
    if not rec:
        return jsonify({"error": "Case not found"}), 404
    return jsonify(rec)


@app.get("/api/cases/<int:case_id>/transcript")
def get_transcript(case_id):
    if not services.get_case(case_id):
        return jsonify({"error": "Case not found"}), 404
    return jsonify({"messages": services.get_messages(case_id)})


@app.patch("/api/cases/<int:case_id>")
def patch_case(case_id):
    if not services.get_case(case_id):
        return jsonify({"error": "Case not found"}), 404
    data = request.get_json(silent=True) or {}
    fields = {}
    if "summary" in data:
        fields["summary"] = (data.get("summary") or "").strip()
    if "target_course" in data:
        fields["target_course"] = (data.get("target_course") or "").strip()
    if fields:
        services.update_case(case_id, fields)
        services.recompute_completion(case_id)
    return jsonify(_case_record(case_id))


@app.post("/api/cases/<int:case_id>/message")
def post_message(case_id):
    case = services.get_case(case_id)
    if not case:
        return jsonify({"error": "Case not found"}), 404

    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "Message is required"}), 400

    # Persist the user turn first (transcript is the audit log).
    services.add_message(case_id, "user", user_message)

    # Build history for Echo, ground in settings + relevant catalog.
    settings = services.get_settings()
    history = [{"role": m["role"], "content": m["content"]}
               for m in services.get_messages(case_id, roles=("user", "assistant"))]
    catalog = services.get_catalog(relevant_to=user_message)

    answer, err = ai.chat(history, settings, catalog)
    if err:
        return jsonify({"error": err}), 502
    services.add_message(case_id, "assistant", answer)

    # Structured extraction -> update Case Record (best-effort).
    history.append({"role": "assistant", "content": answer})
    try:
        extraction, ex_err = ai.extract_case(history)
        if extraction and not ex_err:
            services.merge_extraction(case_id, extraction)
    except Exception:
        app.logger.exception("extraction failed (non-fatal)")
    services.recompute_completion(case_id)

    rec = _case_record(case_id)
    rec["answer"] = answer
    return jsonify(rec)


# ===============================
# Submit, delete, history (Phase 4)
# ===============================
@app.post("/api/cases/<int:case_id>/submit")
def submit_case(case_id):
    case = services.get_case(case_id)
    if not case:
        return jsonify({"error": "Case not found"}), 404
    if case["status"] != services.STATUS_DRAFT:
        return jsonify({"error": f"Case is already {case['status']}."}), 400

    settings = services.get_settings()
    pct = services.recompute_completion(case_id)
    submit_threshold = settings.get("submit_threshold", 80)
    if pct < submit_threshold:
        return jsonify({"error": f"Case must reach {submit_threshold}% to submit "
                                 f"(currently {pct}%)."}), 400

    # Advisory AI confidence (human decides). Best-effort.
    comps = services.get_competencies(case_id)
    evidence = services.get_evidence(case_id)
    conf, rationale = None, None
    try:
        scored, err = ai.score_confidence(case, comps, evidence)
        if scored and not err:
            conf = scored["confidence"]
            rationale = scored["rationale"]
    except Exception:
        app.logger.exception("confidence scoring failed (non-fatal)")

    fields = {"status": services.STATUS_SUBMITTED}
    if conf is not None:
        fields["ai_confidence"] = conf
        fields["ai_confidence_rationale"] = rationale
    services.update_case(case_id, fields)
    # Apply institution routing rules (assignee / flags) on submit.
    services.apply_routing_rules(case_id)
    services.add_message(case_id, "system", "Case submitted for review.")
    return jsonify(_case_record(case_id))


@app.delete("/api/cases/<int:case_id>")
def delete_case_api(case_id):
    case = services.get_case(case_id)
    if not case:
        return jsonify({"error": "Case not found"}), 404
    settings = services.get_settings()
    threshold = settings.get("delete_below_threshold", 50)
    if (case.get("completion_pct") or 0) >= threshold and case["status"] == services.STATUS_DRAFT:
        return jsonify({"error": f"Cases at or above {threshold}% completion can't be "
                                 f"deleted. Continue or submit it instead."}), 400
    if case["status"] not in (services.STATUS_DRAFT,):
        return jsonify({"error": "Submitted cases can't be deleted."}), 400
    services.delete_case(case_id)
    return jsonify({"status": "deleted"})


@app.get("/api/cases/<int:case_id>/detail")
def case_detail(case_id):
    case = services.get_case(case_id)
    if not case:
        return jsonify({"error": "Case not found"}), 404
    return jsonify({
        "case": case,
        "competencies": services.get_competencies(case_id),
        "evidence": services.get_evidence(case_id),
        "messages": services.get_messages(case_id),
        "feedback": services.latest_feedback(case_id),
    })


@app.get("/history")
def history_page():
    return render_template("history.html")


# ===============================
# Evidence API (Phase 3)
# ===============================
import storage


@app.post("/api/cases/<int:case_id>/evidence")
def upload_evidence(case_id):
    case = services.get_case(case_id)
    if not case:
        return jsonify({"error": "Case not found"}), 404
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file provided"}), 400

    data = f.read()
    ok, err = storage.validate(f.filename, len(data))
    if not ok:
        return jsonify({"error": err}), 400

    try:
        stored = storage.save(case_id, f.filename, data, f.mimetype)
    except Exception:
        app.logger.exception("evidence save failed")
        return jsonify({"error": "Could not store the file."}), 500

    extracted = storage.extract_text(f.filename, data, f.mimetype)
    eid = services.add_evidence(case_id, f.filename, len(data), f.mimetype, stored, extracted)

    # AI mapping suggestion against current competencies (best-effort).
    suggestion = None
    comps = services.get_competencies(case_id)
    if comps:
        try:
            sug, sug_err = ai.suggest_mapping(f.filename, extracted, comps)
            if sug and not sug_err and sug.get("competency"):
                suggestion = sug.get("competency")
                services.set_evidence_suggestion(eid, suggestion)
        except Exception:
            app.logger.exception("mapping suggestion failed (non-fatal)")

    services.recompute_completion(case_id)
    rec = _case_record(case_id)
    rec["uploaded_id"] = eid
    rec["suggestion"] = suggestion
    return jsonify(rec)


@app.post("/api/evidence/<int:eid>/link")
def link_evidence_api(eid):
    row = services.get_evidence_row(eid)
    if not row:
        return jsonify({"error": "Evidence not found"}), 404
    data = request.get_json(silent=True) or {}
    comp_id = data.get("competency_id")
    if not comp_id:
        return jsonify({"error": "competency_id required"}), 400
    comp = db.query_one("SELECT id FROM competencies WHERE id = ? AND case_id = ?",
                        [comp_id, row["case_id"]])
    if not comp:
        return jsonify({"error": "Competency not found for this case"}), 400
    services.link_evidence(eid, comp_id)
    services.recompute_completion(row["case_id"])
    return jsonify(_case_record(row["case_id"]))


@app.post("/api/evidence/<int:eid>/unlink")
def unlink_evidence_api(eid):
    row = services.get_evidence_row(eid)
    if not row:
        return jsonify({"error": "Evidence not found"}), 404
    services.unlink_evidence(eid)
    services.recompute_completion(row["case_id"])
    return jsonify(_case_record(row["case_id"]))


@app.delete("/api/evidence/<int:eid>")
def delete_evidence_api(eid):
    row = services.get_evidence_row(eid)
    if not row:
        return jsonify({"error": "Evidence not found"}), 404
    try:
        storage.delete(row)
    except Exception:
        app.logger.exception("storage delete failed (continuing)")
    services.delete_evidence(eid)
    services.recompute_completion(row["case_id"])
    return jsonify(_case_record(row["case_id"]))


@app.get("/api/evidence/<int:eid>/download")
def download_evidence(eid):
    row = services.get_evidence_row(eid)
    if not row:
        return jsonify({"error": "Evidence not found"}), 404
    # Reviewer-gated access to others' files is enforced once auth lands (Phase 5);
    # applicants can fetch their own case evidence.
    try:
        data = storage.get_bytes(row)
    except Exception:
        app.logger.exception("evidence download failed")
        return jsonify({"error": "Could not retrieve the file."}), 500
    from flask import Response
    resp = Response(data, mimetype=row.get("mime_type") or "application/octet-stream")
    resp.headers["Content-Disposition"] = f'inline; filename="{row.get("filename")}"'
    return resp


# ===============================
# Reviewer auth + queue (Phase 5)
# ===============================
import auth
import csv as _csv
import io as _io
from flask import Response, redirect, url_for


@app.get("/reviewer/login")
def reviewer_login_page():
    if auth.is_authenticated():
        return redirect("/reviewer")
    return render_template("reviewer_login.html")


@app.post("/api/reviewer/login")
def reviewer_login():
    data = request.get_json(silent=True) or {}
    reviewer = auth.verify_login(data.get("email"), data.get("password"))
    if not reviewer:
        return jsonify({"error": "Invalid email or password."}), 401
    auth.login_session(reviewer)
    return jsonify({"status": "ok", "name": reviewer.get("name") or reviewer["email"]})


@app.post("/api/reviewer/logout")
def reviewer_logout():
    auth.logout_session()
    return jsonify({"status": "ok"})


@app.get("/reviewer")
def reviewer_queue_page():
    if not auth.is_authenticated():
        return redirect("/reviewer/login")
    return render_template("reviewer_queue.html",
                           reviewer_name=auth.current_reviewer().get("name", "Reviewer"))


@app.get("/api/reviewer/cases")
@auth.require_reviewer
def reviewer_cases():
    status = request.args.get("status", "all")
    q = request.args.get("q", "")
    return jsonify({
        "cases": services.list_review_cases(status, q),
        "counts": services.queue_counts(),
    })


@app.get("/api/reviewer/cases.csv")
@auth.require_reviewer
def reviewer_cases_csv():
    status = request.args.get("status", "all")
    q = request.args.get("q", "")
    rows = services.list_review_cases(status, q)
    buf = _io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(["Case ID", "Applicant", "Target Course", "Status",
                     "Completion %", "AI Confidence", "Date Updated"])
    for r in rows:
        writer.writerow([r.get("case_code"), r.get("applicant_name"),
                         r.get("target_course"), r.get("status"),
                         r.get("completion_pct"), r.get("ai_confidence"),
                         r.get("updated_at")])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=cpl-cases.csv"})


@app.get("/api/reviewer/me")
def reviewer_me():
    r = auth.current_reviewer()
    counts = services.queue_counts() if r else {}
    return jsonify({"authenticated": bool(r), "reviewer": r, "counts": counts})


# ===============================
# Local Dev Entry Point
# ===============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
