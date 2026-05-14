const registerForm = document.getElementById("registerForm");
const message = document.getElementById("authMessage");

async function postJson(url, payload) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || "请求失败");
  return data;
}

registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.textContent = "";
  try {
    await postJson("/api/register", {
      username: document.getElementById("registerUser").value.trim(),
      password: document.getElementById("registerPass").value,
      repeat: document.getElementById("registerRepeat").value,
      code: document.getElementById("registerCode").value.trim(),
    });
    window.location.href = "/app";
  } catch (err) {
    message.textContent = err.message;
  }
});
