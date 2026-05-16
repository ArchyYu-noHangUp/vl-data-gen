const $ = (id) => document.getElementById(id);

async function initUser() {
  $("manageLink").hidden = true;
  const resp = await fetch("/api/me");
  const data = await resp.json();
  if (!data.user) {
    window.location.href = "/";
    return;
  }
  if (data.appearance === "simple") {
    document.body.classList.add("simple-appearance");
    document.title = "评测数据采集与标注";
    $("appTitle").textContent = "评测数据采集与标注";
    $("versionBadge").hidden = true;
    $("userInfo").hidden = true;
  }
  $("versionBadge").textContent = `版本 ${data.version || "0.2.2"}`;
  $("userInfo").textContent = `${data.user.username}，上传问题图片与答案图片，自动生成题目文件夹和校核结果。`;
  $("manageLink").hidden = data.user.role !== "admin";
}

function renderList(input, output) {
  const files = Array.from(input.files || []);
  output.innerHTML = "";
  for (const file of files) {
    const row = document.createElement("div");
    row.textContent = `${file.name} (${Math.ceil(file.size / 1024)} KB)`;
    output.appendChild(row);
  }
}

$("question_images").addEventListener("change", () => {
  renderList($("question_images"), $("questionList"));
});

$("answer_images").addEventListener("change", () => {
  renderList($("answer_images"), $("answerList"));
});

$("suggestionBtn").addEventListener("click", async () => {
  const content = $("suggestionText").value.trim();
  const status = $("suggestionStatus");
  status.textContent = "";
  if (!content) {
    status.textContent = "请先填写建议";
    return;
  }
  $("suggestionBtn").disabled = true;
  status.textContent = "正在提交...";
  try {
    const resp = await fetch("/api/suggestions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      if (resp.status === 401) {
        throw new Error("登录已失效，请重新登录后提交");
      }
      throw new Error(formatError(data, "提交失败"));
    }
    $("suggestionText").value = "";
    status.textContent = "已提交，管理员可在系统管理中查看";
  } catch (err) {
    status.textContent = `提交失败：${err.message}`;
  } finally {
    $("suggestionBtn").disabled = false;
  }
});

$("processBtn").addEventListener("click", async () => {
  const btn = $("processBtn");
  const log = $("log");
  const result = $("result");
  btn.disabled = true;
  result.hidden = true;
  log.textContent = "开始上传并调用多模态模型，请等待...\n";

  const form = new FormData();
  form.append("url", $("url").value.trim());
  form.append("model_name", $("model_name").value.trim());
  form.append("api_key", $("api_key").value.trim());
  form.append("data_source", $("data_source").value.trim());
  for (const file of $("question_images").files) {
    form.append("question_images", file);
  }
  for (const file of $("answer_images").files) {
    form.append("answer_images", file);
  }

  try {
    const resp = await fetch("/api/process", { method: "POST", body: form });
    let data = await readJsonResponse(resp);
    if (!data && resp.ok) {
      log.textContent += "处理已结束但响应为空，正在恢复最新结果...\n";
      const latestResp = await fetch("/api/latest-result");
      data = await readJsonResponse(latestResp);
      if (!latestResp.ok) {
        throw new Error(data?.error || "无法恢复最新结果");
      }
    }
    if (!resp.ok) {
      throw new Error(formatError(data, "处理失败"));
    }
    renderLogs(data);
    if (data.status === "completed") {
      showResult(data);
    } else {
      data = await pollJob(data.job_id);
      showResult(data);
    }
  } catch (err) {
    log.textContent += `错误：${err.message}\n`;
  } finally {
    btn.disabled = false;
  }
});

function renderLogs(data) {
  const logs = data?.logs || [];
  $("log").textContent = logs.join("\n") + (logs.length ? "\n" : "");
}

function showResult(data) {
  if (data.status === "failed") {
    throw new Error(data.error || "处理失败");
  }
  $("log").textContent += "处理完成。\n";
  $("summary").textContent = `数据处理ID：${data.job_id}；题目数量：${data.question_count}，题图数量：${data.figure_count}，答案文本数量：${data.answer_count}`;
  $("resultLink").href = data.result_url;
  $("result").hidden = false;
}

async function pollJob(jobId) {
  if (!jobId) {
    throw new Error("服务端没有返回 job_id");
  }
  let consecutiveErrors = 0;
  while (true) {
    await sleep(1000);
    let resp;
    let data;
    try {
      resp = await fetch(`/api/status/${encodeURIComponent(jobId)}`);
      data = await readJsonResponse(resp);
    } catch (err) {
      consecutiveErrors += 1;
      $("log").textContent += `状态查询暂时失败，正在重试（${consecutiveErrors}/30）：${err.message}\n`;
      if (consecutiveErrors >= 30) {
        throw new Error("获取任务状态失败，请稍后刷新页面或查看最新结果");
      }
      continue;
    }
    if (!resp.ok) {
      consecutiveErrors += 1;
      $("log").textContent += `状态查询暂时失败，正在重试（${consecutiveErrors}/30）：${data?.error || resp.status}\n`;
      if (consecutiveErrors >= 30) {
        throw new Error(formatError(data, "获取任务状态失败"));
      }
      continue;
    }
    consecutiveErrors = 0;
    renderLogs(data);
    if (data.status === "completed") {
      return data;
    }
    if (data.status === "failed") {
      throw new Error(data.error || "处理失败");
    }
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function formatError(data, fallback) {
  if (!data) {
    return fallback;
  }
  if (data.error) {
    return data.error;
  }
  if (typeof data.detail === "string") {
    return data.detail;
  }
  if (Array.isArray(data.detail)) {
    return data.detail.map((item) => item.msg || JSON.stringify(item)).join("；");
  }
  return fallback;
}

async function readJsonResponse(resp) {
  const text = await resp.text();
  if (!text.trim()) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch (err) {
    throw new Error(`服务端返回内容不是 JSON：${text.slice(0, 200)}`);
  }
}

initUser().catch(() => {
  window.location.href = "/";
});
