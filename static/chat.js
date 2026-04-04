const msgEl = document.getElementById("msg");
const outEl = document.getElementById("out");
const sendBtn = document.getElementById("send");
const clearBtn = document.getElementById("clear");
const copyBtn = document.getElementById("copy");
const statusText = document.getElementById("statusText");

function setStatus(text) { 
  statusText.textContent = text; 
}

// Function to lock and unlock the UI
function setBusy(isBusy) {
  sendBtn.disabled = isBusy;
  msgEl.disabled = isBusy;
  copyBtn.disabled = isBusy;
  clearBtn.disabled = isBusy;
  setStatus(isBusy ? "Thinking..." : "Ready");
}

async function sendMessage() {
  const msg = msgEl.value.trim();
  if (!msg) {
    outEl.textContent = "Please type a message first.";
    return;
  }

  // Lock UI while waiting for Azure OpenAI
  setBusy(true);
  outEl.textContent = "Thinking...";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg }),
    });

    const text = await res.text();
    let data = null;
    try { data = JSON.parse(text); } catch (_) {}

    if (!res.ok) {
      outEl.textContent = data?.error ? `Error (${res.status}): ${data.error}` : `Error (${res.status}): ${text}`;
      outEl.classList.add("error");
    } else {
      outEl.textContent = data?.answer ?? text;
      outEl.classList.remove("error");
      // Clear the input box so the user can easily type their next answer
      msgEl.value = ""; 
    }
  } catch (e) {
    outEl.textContent = `Network error: ${e}`;
    outEl.classList.add("error");
  } finally {
    // UNLOCK THE UI so the user can reply
    setBusy(false);
    msgEl.focus();
  }
}

// Event Listeners
sendBtn.addEventListener("click", sendMessage);

// Allow sending with Ctrl+Enter or Cmd+Enter
msgEl.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    sendMessage();
  }
});

// Clear button logic
clearBtn.addEventListener("click", () => {
  msgEl.value = "";
  outEl.textContent = "Your answer will show up here…";
  outEl.classList.remove("error");
  msgEl.focus();
});

// Copy button logic
copyBtn.addEventListener("click", async () => {
  const text = outEl.textContent || "";
  try {
    await navigator.clipboard.writeText(text);
    const old = copyBtn.textContent;
    copyBtn.textContent = "Copied!";
    setTimeout(() => (copyBtn.textContent = old), 900);
  } catch {
    const range = document.createRange();
    range.selectNodeContents(outEl);
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(range);
    copyBtn.textContent = "Select & Copy";
    setTimeout(() => (copyBtn.textContent = "Copy"), 1100);
  }
});