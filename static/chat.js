document.getElementById("send").addEventListener("click", async () => {
  const msg = document.getElementById("msg").value.trim();
  const out = document.getElementById("out");
  out.textContent = "Thinking...";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg }),
    });

    const data = await res.json();
    if (!res.ok) {
      out.textContent = data.error || "Request failed";
      return;
    }
    out.textContent = data.answer || "";
  } catch (e) {
    out.textContent = "Network error";
  }
});
