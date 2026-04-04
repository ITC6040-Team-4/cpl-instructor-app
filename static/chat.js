document.getElementById("send").addEventListener("click", async () => {
  const msg = document.getElementById("msg").value.trim();
  const out = document.getElementById("out");

  if (!msg) {
    out.textContent = "Please type a message first.";
    return;
  }

  out.textContent = "Thinking...";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg }),
    });

    const text = await res.text();   // read raw body first
    let data = null;
    try { data = JSON.parse(text); } catch (_) {}

    if (!res.ok) {
      out.textContent = data?.error
        ? `Error (${res.status}): ${data.error}`
        : `Error (${res.status}): ${text}`;
      return;
    }

    out.textContent = data?.answer ?? text;
  } catch (e) {
    out.textContent = `Network error: ${e}`;
  }
});
