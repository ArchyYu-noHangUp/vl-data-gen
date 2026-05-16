const message = document.getElementById("authMessage");

async function applyAppearance() {
  const resp = await fetch("/api/appearance");
  const data = await resp.json().catch(() => ({}));
  if (data.appearance !== "simple") {
    return;
  }
  document.body.classList.add("simple-appearance");
  document.title = "评测数据采集与标注";
  document.getElementById("welcomeTitle").textContent = "评测数据采集与标注";
  document.getElementById("welcomeSubtitle").hidden = true;
}

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

applyAppearance().catch(() => {});
checkSession().catch(() => {});
