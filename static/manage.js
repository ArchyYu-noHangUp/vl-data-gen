async function loadStats() {
  const resp = await fetch("/api/admin/stats");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    document.getElementById("statsBody").innerHTML = `<tr><td colspan="3">${data.error || "加载失败"}</td></tr>`;
    return;
  }
  document.getElementById("statsBody").innerHTML = data.users
    .map(
      (user) =>
        `<tr><td>${escapeHtml(user.username)}</td><td>${user.collected}</td><td>${user.reviewed}</td></tr>`
    )
    .join("");
}

async function loadSettings() {
  const resp = await fetch("/api/admin/settings");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    document.getElementById("registerCodeStatus").textContent = data.error || "加载失败";
    return;
  }
  document.getElementById("registerCodeInput").value = data.register_code || "";
}

async function saveRegisterCode() {
  const status = document.getElementById("registerCodeStatus");
  status.textContent = "";
  const registerCode = document.getElementById("registerCodeInput").value.trim();
  try {
    const resp = await fetch("/api/admin/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ register_code: registerCode }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "保存失败");
    status.textContent = "已保存";
  } catch (err) {
    status.textContent = err.message;
  }
}

async function loadSuggestions() {
  const resp = await fetch("/api/admin/suggestions");
  const data = await resp.json().catch(() => ({}));
  const list = document.getElementById("suggestionsList");
  if (!resp.ok) {
    list.textContent = data.error || "加载失败";
    return;
  }
  const suggestions = data.suggestions || [];
  if (!suggestions.length) {
    list.textContent = "暂无修改建议";
    return;
  }
  list.innerHTML = suggestions
    .map(
      (item) => `
        <article class="suggestion-item">
          <div><strong>${escapeHtml(item.username)}</strong><span>${escapeHtml(item.created_at)}</span></div>
          <p>${escapeHtml(item.content)}</p>
        </article>`
    )
    .join("");
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

document.getElementById("saveRegisterCode").addEventListener("click", saveRegisterCode);
loadStats();
loadSettings();
loadSuggestions();
