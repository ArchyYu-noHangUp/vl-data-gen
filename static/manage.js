async function loadStats() {
  const resp = await fetch("/api/admin/stats");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    document.getElementById("statsBody").innerHTML = `<tr><td colspan="4">${data.error || "加载失败"}</td></tr>`;
    return;
  }
  document.getElementById("statsBody").innerHTML = data.users
    .map((user) => {
      const disabled = user.username === "admin" ? "disabled" : "";
      return `
        <tr>
          <td>${escapeHtml(user.username)}</td>
          <td>${user.collected}</td>
          <td>${user.reviewed}</td>
          <td>
            <select data-role-user="${escapeHtml(user.username)}" ${disabled}>
              <option value="user" ${user.role !== "admin" ? "selected" : ""}>普通账户</option>
              <option value="admin" ${user.role === "admin" ? "selected" : ""}>管理员</option>
            </select>
          </td>
        </tr>`;
    })
    .join("");
  for (const select of document.querySelectorAll("[data-role-user]")) {
    select.addEventListener("change", () => saveUserRole(select.dataset.roleUser, select.value));
  }
}

async function saveUserRole(username, role) {
  const resp = await fetch("/api/admin/users/role", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, role }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    alert(data.error || "权限保存失败");
    await loadStats();
  }
}

async function loadSettings() {
  const resp = await fetch("/api/admin/settings");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    document.getElementById("registerCodeStatus").textContent = data.error || "加载失败";
    document.getElementById("appearanceStatus").textContent = data.error || "加载失败";
    document.getElementById("modelConfigStatus").textContent = data.error || "加载失败";
    document.getElementById("sampleDatasetPathStatus").textContent = data.error || "加载失败";
    return;
  }
  document.getElementById("registerCodeInput").value = data.register_code || "";
  document.getElementById("appearanceSelect").value = data.appearance || "standard";
  document.getElementById("modelUrlInput").value = data.model_url || "";
  document.getElementById("modelNameInput").value = data.model_name || "";
  document.getElementById("modelApiKeyInput").placeholder = data.model_api_key_configured ? "已配置，留空则不修改" : "尚未配置，请填写 API Key";
  document.getElementById("sampleDatasetPathInput").value = data.sample_dataset_path || "";
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

async function saveAppearance() {
  const status = document.getElementById("appearanceStatus");
  status.textContent = "";
  const appearance = document.getElementById("appearanceSelect").value;
  try {
    const resp = await fetch("/api/admin/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ appearance }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "保存失败");
    status.textContent = "已保存，刷新页面后生效";
  } catch (err) {
    status.textContent = err.message;
  }
}

async function saveModelConfig() {
  const status = document.getElementById("modelConfigStatus");
  status.textContent = "";
  const payload = {
    model_url: document.getElementById("modelUrlInput").value.trim(),
    model_name: document.getElementById("modelNameInput").value.trim(),
  };
  const apiKey = document.getElementById("modelApiKeyInput").value.trim();
  if (apiKey) {
    payload.model_api_key = apiKey;
  }
  try {
    const resp = await fetch("/api/admin/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "保存失败");
    document.getElementById("modelApiKeyInput").value = "";
    document.getElementById("modelApiKeyInput").placeholder = data.model_api_key_configured ? "已配置，留空则不修改" : "尚未配置，请填写 API Key";
    status.textContent = "已保存";
  } catch (err) {
    status.textContent = err.message;
  }
}

async function saveSampleDatasetPath() {
  const status = document.getElementById("sampleDatasetPathStatus");
  status.textContent = "";
  const samplePath = document.getElementById("sampleDatasetPathInput").value.trim();
  try {
    const resp = await fetch("/api/admin/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sample_dataset_path: samplePath }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "保存失败");
    document.getElementById("sampleDatasetPathInput").value = data.sample_dataset_path || samplePath;
    status.textContent = "已保存并移动样本集";
    await loadSampleStatus();
  } catch (err) {
    status.textContent = err.message;
  }
}

async function loadFinalItems() {
  const resp = await fetch("/api/admin/final-items");
  const data = await resp.json().catch(() => ({}));
  const body = document.getElementById("finalItemsBody");
  if (!resp.ok) {
    body.innerHTML = `<tr><td colspan="8">${data.error || "加载失败"}</td></tr>`;
    return;
  }
  const items = data.items || [];
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="8">暂无待处理最终结果</td></tr>`;
    return;
  }
  body.innerHTML = items
    .map(
      (item) => `
        <tr data-job-id="${escapeAttr(item.job_id)}">
          <td class="job-id-cell">${escapeHtml(item.job_id)}</td>
          <td><input data-field="data_source" value="${escapeAttr(item.data_source)}" /></td>
          <td><input data-field="chapter" value="${escapeAttr((item.chapters || []).join("、"))}" /></td>
          <td><button type="button" class="link-button" data-action="show-qids" data-qids="${escapeAttr((item.qids || []).join("、"))}">查看题目编号</button></td>
          <td><input data-field="username" value="${escapeAttr(item.username)}" /></td>
          <td>${escapeHtml(item.generated_at)}</td>
          <td><a href="/static/result.html?job_id=${encodeURIComponent(item.job_id)}" target="_blank">查看校核结果</a></td>
          <td class="row-actions">
            <button type="button" data-action="accept">保存</button>
            <button type="button" class="secondary-action" data-action="download">下载zip</button>
            <button type="button" class="secondary-action" data-action="discard">放弃</button>
          </td>
        </tr>`
    )
    .join("");
  body.addEventListener("click", handleFinalAction, { once: true });
}

async function loadSampleStatus() {
  const resp = await fetch("/api/admin/sample-status");
  const data = await resp.json().catch(() => ({}));
  const body = document.getElementById("sampleStatusBody");
  if (!resp.ok) {
    body.innerHTML = `<tr><td colspan="3">${data.error || "加载失败"}</td></tr>`;
    return;
  }
  const items = data.items || [];
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="3">暂无样本数据</td></tr>`;
    return;
  }
  body.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${escapeHtml(item.data_source)}</td>
          <td><button type="button" class="link-button" data-chapters="${escapeAttr((item.chapters || []).join("、"))}">${item.chapter_count}</button></td>
          <td>${item.question_count}</td>
        </tr>`
    )
    .join("");
  for (const button of body.querySelectorAll("[data-chapters]")) {
    button.addEventListener("click", () => {
      alert(button.dataset.chapters || "暂无章节");
    });
  }
}

async function handleFinalAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    document.getElementById("finalItemsBody").addEventListener("click", handleFinalAction, { once: true });
    return;
  }
  const action = button.dataset.action;
  if (action === "show-qids") {
    alert(button.dataset.qids || "暂无题目编号");
    document.getElementById("finalItemsBody").addEventListener("click", handleFinalAction, { once: true });
    return;
  }
  const row = button.closest("tr[data-job-id]");
  const jobId = row.dataset.jobId;
  if (action === "discard") {
    if (confirm("确定放弃并删除该数据处理ID对应的全部临时数据？")) await postFinalAction(jobId, "discard");
  } else if (action === "accept") {
    const ok = await updateFinalJob(row, jobId);
    if (!ok) {
      await loadFinalItems();
      return;
    }
    await postFinalAction(jobId, "save");
  } else if (action === "download") {
    await downloadFinalZip(jobId);
    document.getElementById("finalItemsBody").addEventListener("click", handleFinalAction, { once: true });
    return;
  }
  await loadFinalItems();
}

function rowPayload(row) {
  const payload = {};
  for (const input of row.querySelectorAll("[data-field]")) {
    payload[input.dataset.field] = input.value.trim();
  }
  return payload;
}

async function updateFinalJob(row, jobId) {
  const resp = await fetch(`/api/admin/final-jobs/${encodeURIComponent(jobId)}/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rowPayload(row)),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    alert(data.error || "保存失败");
    return false;
  }
  return true;
}

async function postFinalAction(jobId, action) {
  const resp = await fetch(`/api/admin/final-jobs/${encodeURIComponent(jobId)}/${action}`, { method: "POST" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) alert(data.error || "操作失败");
}

async function downloadFinalZip(jobId) {
  const resp = await fetch("/api/make-review-zip", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_id: jobId }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    alert(data.error || "下载zip失败");
    return;
  }
  if (data.download_url) {
    window.location.href = data.download_url;
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

function escapeAttr(text) {
  return escapeHtml(text).replace(/`/g, "&#96;");
}

document.getElementById("saveRegisterCode").addEventListener("click", saveRegisterCode);
document.getElementById("saveAppearance").addEventListener("click", saveAppearance);
document.getElementById("saveModelConfig").addEventListener("click", saveModelConfig);
document.getElementById("saveSampleDatasetPath").addEventListener("click", saveSampleDatasetPath);
loadStats();
loadSettings();
loadFinalItems();
loadSampleStatus();
loadSuggestions();
