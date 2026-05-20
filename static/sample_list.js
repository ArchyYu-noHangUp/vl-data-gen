const params = new URLSearchParams(window.location.search);
const source = params.get("source") || "";
const body = document.getElementById("sampleListBody");
const meta = document.getElementById("sampleListMeta");
const downloadInfo = document.getElementById("downloadInfo");
const remarkDialog = document.getElementById("remarkDialog");
const remarkEditor = document.getElementById("remarkEditor");
const remarkSave = document.getElementById("remarkSave");
const remarkCancel = document.getElementById("remarkCancel");
let activeRemarkItem = null;
const pendingTypeset = new Set();
let typesetTimer = null;
let typesetWaits = 0;

window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin) return;
  if (event.data?.type === "vl-data-gen-sample-status-updated") {
    load();
  }
});

window.addEventListener("storage", (event) => {
  if (event.key === "vlDataGenSampleStatusUpdated" && event.newValue) {
    load();
  }
});

function escapeHtml(text) {
  return String(text || "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

function sampleAsset(item, filename) {
  return `/sample-asset/${encodeURIComponent(source)}/${encodeURIComponent(item.sample_id)}/${encodeURIComponent(filename)}`;
}

function mathText(text, display = false) {
  const value = String(text || "").trim();
  if (!value) return "";
  if (/\\\(|\\\[/.test(value)) {
    return value;
  }
  if (/\$/.test(value)) {
    return value;
  }
  if (display && /[\\_^{}]/.test(value)) {
    return `\\[${value}\\]`;
  }
  return escapeHtml(value);
}

function answerMath(text) {
  const value = String(text || "").trim();
  if (!value) return "";
  if (/\\\(|\\\[|\$/.test(value)) {
    return value;
  }
  return value
    .split(/(，|,|；|;)/)
    .map((part) => {
      if (/^(，|,|；|;)$/.test(part)) return `${escapeHtml(part)} `;
      const item = part.trim();
      if (!item) return "";
      if (/[\\_^{}=]/.test(item)) return `\\(${item}\\)`;
      return escapeHtml(item);
    })
    .join("");
}

function queueTypeset(element) {
  pendingTypeset.add(element);
  scheduleTypeset();
}

function scheduleTypeset() {
  if (typesetTimer) return;
  typesetTimer = window.setTimeout(flushTypeset, 80);
}

function flushTypeset() {
  typesetTimer = null;
  if (!window.MathJax?.typesetPromise) {
    typesetWaits += 1;
    if (typesetWaits < 120) scheduleTypeset();
    return;
  }
  typesetWaits = 0;
  const elements = Array.from(pendingTypeset).filter((element) => element.isConnected);
  pendingTypeset.clear();
  if (elements.length) {
    window.MathJax.typesetPromise(elements).catch(() => {});
  }
}

function renderQuestion(item) {
  const figures = (item.figures || []).map((fig) => `<img src="${sampleAsset(item, fig)}" alt="">`).join("");
  return `
    <div class="preview-body sample-question-box">
      <div class="sample-part-title">问题</div>
      <div class="sample-math-content">${mathText(item.question)}</div>
      <div class="image-list">${figures}</div>
      <div class="sample-part-title">答案</div>
      <div class="sample-math-content">${answerMath(item.answer)}</div>
    </div>`;
}

async function load() {
  const resp = await fetch(`/api/admin/sample-sources/${encodeURIComponent(source)}/samples`);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    body.innerHTML = `<tr><td colspan="8">${data.error || "加载失败"}</td></tr>`;
    return;
  }
  meta.textContent = `数据来源：${data.source}`;
  downloadInfo.href = data.info_download_url;
  const items = (data.items || []).slice().sort((a, b) => questionKey(a.sample_id).localeCompare(questionKey(b.sample_id), "zh-Hans-u-kn-true"));
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="8">暂无样本</td></tr>`;
    return;
  }
  body.innerHTML = items.map((item) => `
    <tr>
      <td>${item.index}</td>
      <td>${escapeHtml(item.data_source)}</td>
      <td>${escapeHtml(item.sample_id)}</td>
      <td>${escapeHtml(item.username)}</td>
      <td>${escapeHtml(item.created_at)}</td>
      <td class="sample-question-cell">${renderQuestion(item)}</td>
      <td><a href="/static/sample_review.html?source=${encodeURIComponent(source)}&sample=${encodeURIComponent(item.sample_id)}" target="_blank">${escapeHtml(item.status || "未审核")}</a></td>
      <td><button type="button" class="link-button remark-button" data-sample="${escapeHtml(item.sample_id)}">${escapeHtml(item.remark || "填写备注")}</button></td>
    </tr>`).join("");
  for (const button of body.querySelectorAll(".remark-button")) {
    button.addEventListener("click", () => {
      const item = items.find((entry) => entry.sample_id === button.dataset.sample);
      openRemarkDialog(item);
    });
  }
  queueTypeset(body);
}

function questionKey(value) {
  return String(value || "").replace(/(\d+)/g, (match) => match.padStart(8, "0"));
}

function openRemarkDialog(item) {
  activeRemarkItem = item;
  remarkEditor.value = item?.remark || "";
  remarkDialog.hidden = false;
  remarkEditor.focus();
}

function closeRemarkDialog() {
  activeRemarkItem = null;
  remarkDialog.hidden = true;
  remarkEditor.value = "";
}

async function saveRemark() {
  if (!activeRemarkItem) return;
  const resp = await fetch(`/api/admin/sample-sources/${encodeURIComponent(source)}/samples/${encodeURIComponent(activeRemarkItem.sample_id)}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: activeRemarkItem.status || "未审核", remark: remarkEditor.value.trim() }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    alert(data.error || "备注保存失败");
    return;
  }
  closeRemarkDialog();
  await load();
}

remarkSave.addEventListener("click", () => saveRemark());
remarkCancel.addEventListener("click", closeRemarkDialog);
remarkDialog.addEventListener("click", (event) => {
  if (event.target === remarkDialog) closeRemarkDialog();
});

load();
