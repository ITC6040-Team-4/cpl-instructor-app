const msgEl = document.getElementById("msg");
const chatHistory = document.getElementById("chatHistory"); // NEW DOM Target
const sendBtn = document.getElementById("send");
const clearBtn = document.getElementById("clear");
const copyBtn = document.getElementById("copy");
const statusText = document.getElementById("statusText");

const fileUpload = document.getElementById("fileUpload");
const attachBtn = document.getElementById("attachBtn");
const filePreview = document.getElementById("filePreview");

function setStatus(text) { 
  statusText.textContent = text; 
}

function setBusy(isBusy) {
  sendBtn.disabled = isBusy;
  msgEl.disabled = isBusy;
  copyBtn.disabled = isBusy;
  clearBtn.disabled = isBusy;
  attachBtn.disabled = isBusy;
  setStatus(isBusy ? "Thinking..." : "Ready");
}

// NEW: Helper function to build chat bubbles
function appendMessage(role, text) {
  const div = document.createElement("div");
  div.className = `msg-bubble msg-${role}`;
  div.textContent = text;
  chatHistory.appendChild(div);
  
  // Auto-scroll to the bottom of the chat history
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

attachBtn.addEventListener("click", () => {
  fileUpload.click();
});

fileUpload.addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) {
    filePreview.textContent = "";
    return;
  }
  filePreview.textContent = `📎 Attached: ${file.name}`;
  filePreview.style.color = "var(--accent2)";
});

async function sendMessage() {
  const msg = msgEl.value.trim();
  const file = fileUpload.files[0];
  
  if (!msg && !file) {
    alert("Please type a message or attach a file first.");
    return;
  }

  // 1. Show the user's message in the UI immediately
  let displayMsg = msg;
  if (file) {
    displayMsg = `📎 [Attached File: ${file.name}]\n${msg}`;
  }
  appendMessage("user", displayMsg);

  setBusy(true);

  // Show a temporary "Thinking..." bubble
  const thinkingDiv = document.createElement("div");
  thinkingDiv.className = "msg-bubble msg-system";
  thinkingDiv.id = "thinkingIndicator";
  thinkingDiv.textContent = "AI is evaluating...";
  chatHistory.appendChild(thinkingDiv);
  chatHistory.scrollTop = chatHistory.scrollHeight;

  const formData = new FormData();
  formData.append("message", msg);
  if (file) {
    formData.append("file", file);
  }

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      body: formData,
    });

    const text = await res.text();
    let data = null;
    try { data = JSON.parse(text); } catch (_) {}

    // Remove the thinking bubble
    const tInd = document.getElementById("thinkingIndicator");
    if(tInd) tInd.remove();

    if (!res.ok) {
      appendMessage("system", data?.error ? `Error: ${data.error}` : `Error: ${text}`);
    } else {
      // 2. Append the AI's response to the UI
      appendMessage("ai", data?.answer ?? text);
      
      // Clear inputs
      msgEl.value = ""; 
      fileUpload.value = "";
      filePreview.textContent = "";
    }
  } catch (e) {
    const tInd = document.getElementById("thinkingIndicator");
    if(tInd) tInd.remove();
    appendMessage("system", `Network error: ${e}`);
  } finally {
    setBusy(false);
    msgEl.focus();
  }
}

sendBtn.addEventListener("click", sendMessage);

msgEl.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    sendMessage();
  }
});

// Clears the UI history and resets to the default message
clearBtn.addEventListener("click", () => {
  msgEl.value = "";
  fileUpload.value = "";
  filePreview.textContent = "";
  chatHistory.innerHTML = '<div class="msg-bubble msg-system">Session started. Your conversation history will appear here.</div>';
  msgEl.focus();
});

// Copies the entire transcript to the clipboard
copyBtn.addEventListener("click", async () => {
  // Grab all messages except the system messages
  const transcript = Array.from(chatHistory.querySelectorAll('.msg-bubble:not(.msg-system)'))
                          .map(el => (el.classList.contains('msg-user') ? "User:\n" : "Interviewer:\n") + el.textContent)
                          .join('\n\n---\n\n');
  try {
    await navigator.clipboard.writeText(transcript);
    const old = copyBtn.textContent;
    copyBtn.textContent = "Copied!";
    setTimeout(() => (copyBtn.textContent = old), 900);
  } catch {
    alert("Failed to copy transcript.");
  }
});

// NEW: Submit Application Logic
const submitAppBtn = document.getElementById("submitApp");

submitAppBtn.addEventListener("click", async () => {
  if (!confirm("Are you sure you want to finish the interview and send this transcript to your advisor?")) return;

  submitAppBtn.disabled = true;
  submitAppBtn.textContent = "⏳ Sending...";
  appendMessage("system", "Packaging your transcript and sending to the faculty advisor...");

  try {
    const res = await fetch("/api/submit", { method: "POST" });
    const data = await res.json();

    if (!res.ok) {
      appendMessage("system", `❌ Failed to submit: ${data.error}`);
    } else {
      appendMessage("system", `✅ Success: ${data.status}`);
      if (data.summary) {
        appendMessage("system", "Here is a copy of what was sent:\n\n" + data.summary);
      }
      // Congratulations Pop-up Message
      alert("Congratulations! Your CPL application has been successfully submitted to your advisor.");
    }
  } catch (e) {
    appendMessage("system", `❌ Network error during submission: ${e}`);
  } finally {
    submitAppBtn.disabled = false;
    submitAppBtn.textContent = "✉️ Submit to Advisor";
  }
});