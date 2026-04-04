const msgEl = document.getElementById("msg");
const outEl = document.getElementById("out");
const sendBtn = document.getElementById("send");
const clearBtn = document.getElementById("clear");
const copyBtn = document.getElementById("copy");
const statusText = document.getElementById("statusText");

// File upload elements
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
  attachBtn.disabled = isBusy; // Lock attach button while thinking
  setStatus(isBusy ? "Thinking..." : "Ready");
}

// 1. TRIGGER THE HIDDEN FILE INPUT WHEN ATTACH IS CLICKED
attachBtn.addEventListener("click", () => {
  fileUpload.click();
});

// 2. SHOW THE FILENAME WHEN A FILE IS SELECTED
fileUpload.addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) {
    filePreview.textContent = "";
    return;
  }
  filePreview.textContent = `📎 Attached: ${file.name}`;
  filePreview.style.color = "var(--accent2)";
});

// 3. SEND THE MESSAGE AND FILE TO THE BACKEND
async function sendMessage() {
  const msg = msgEl.value.trim();
  const file = fileUpload.files[0];
  
  if (!msg && !file) {
    outEl.textContent = "Please type a message or attach a file first.";
    outEl.classList.add("error");
    return;
  }

  setBusy(true);
  outEl.textContent = "Thinking...";
  outEl.classList.remove("error");

  const formData = new FormData();
  formData.append("message", msg);
  if (file) {
    formData.append("file", file);
  }

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      body: formData, // Sending as FormData so Flask can read the file
    });

    const text = await res.text();
    let data = null;
    try { data = JSON.parse(text); } catch (_) {}

    if (!res.ok) {
      outEl.textContent = data?.error ? `Error (${res.status}): ${data.error}` : `Error (${res.status}): ${text}`;
      outEl.classList.add("error");
    } else {
      outEl.textContent = data?.answer ?? text;
      
      // Clear inputs on success
      msgEl.value = ""; 
      fileUpload.value = "";
      filePreview.textContent = "";
    }
  } catch (e) {
    outEl.textContent = `Network error: ${e}`;
    outEl.classList.add("error");
  } finally {
    setBusy(false);
    msgEl.focus();
  }
}

// Event Listeners for Buttons and Keyboard
sendBtn.addEventListener("click", sendMessage);

msgEl.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    sendMessage();
  }
});

clearBtn.addEventListener("click", () => {
  msgEl.value = "";
  fileUpload.value = "";
  filePreview.textContent = "";
  outEl.textContent = "Your answer will show up here…";
  outEl.classList.remove("error");
  msgEl.focus();
});

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