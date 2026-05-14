const message = document.getElementById("authMessage");

async function checkSession() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("error") === "login") {
    message.textContent = "用户名或密码错误";
    return;
  }
  const resp = await fetch("/api/me");
  const data = await resp.json();
  if (data.user) {
    window.location.href = "/app";
  }
}

checkSession().catch(() => {});
