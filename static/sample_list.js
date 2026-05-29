const params = new URLSearchParams(window.location.search);
const source = params.get("source") || "";
const body = document.getElementById("sampleListBody");
const meta = document.getElementById("sampleListMeta");
const downloadInfo = document.getElementById("downloadInfo");
const questionDialog = document.getElementById("questionDialog");
const questionDialogTitle = document.getElementById("questionDialogTitle");
const questionDialogBody = document.getElementById("questionDialogBody");
const questionDialogClose = document.getElementById("questionDialogClose");
let currentItems = [];

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

function sampleDownload(item) {
  return `/api/admin/sample-sources/${encodeURIComponent(source)}/samples/${encodeURIComponent(item.sample_id)}/download`;
}

function plainText(text) {
  return String(text || "")
    .replace(/!\[[^\]]*]\([^)]+\)/g, "")
    .replace(/\\\((.*?)\\\)/g, "$1")
    .replace(/\\\[(.*?)\\\]/gs, "$1")
    .replace(/\$\$(.*?)\$\$/gs, "$1")
    .replace(/\$(.*?)\$/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function mathContent(text) {
  return escapeHtml(text).replace(/\n/g, "<br>");
}

function answerMath(text) {
  const value = String(text || "").trim();
  if (!value) return "";
  if (/\\\(|\\\[|\$/.test(value)) {
    return mathContent(value);
  }
  return value
    .split(/(，|,|；|;)/)
    .map((part) => {
      if (/^(，|,|；|;)$/.test(part)) return `${escapeHtml(part)} `;
      const item = part.trim();
      if (!item) return "";
      if (/[\\_^{}=]/.test(item)) return `\\(${escapeHtml(item)}\\)`;
      return escapeHtml(item);
    })
    .join("");
}

function typesetDialog(waitCount = 0) {
  if (window.MathJax?.typesetPromise) {
    window.MathJax.typesetPromise([questionDialogBody]).catch(() => {});
    return;
  }
  if (waitCount < 80) {
    window.setTimeout(() => typesetDialog(waitCount + 1), 100);
  }
}

function truncateChars(text, maxLength = 20) {
  const chars = Array.from(plainText(text));
  if (chars.length <= maxLength) return chars.join("");
  return `${chars.slice(0, maxLength).join("")}...`;
}

function renderQuestion(item) {
  return `<button type="button" class="sample-question-summary" data-sample="${escapeHtml(item.sample_id)}">${escapeHtml(truncateChars(item.question))}</button>`;
}

function statusCell(item) {
  const status = item.status || "未审核";
  if (status === "已审核") {
    return `<span class="status-text approved-status">${escapeHtml(status)}</span>`;
  }
  return `<a href="/static/sample_review.html?source=${encodeURIComponent(source)}&sample=${encodeURIComponent(item.sample_id)}" target="_blank">${escapeHtml(status)}</a>`;
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
  currentItems = (data.items || []).slice().sort((a, b) => questionKey(a.sample_id).localeCompare(questionKey(b.sample_id), "zh-Hans-u-kn-true"));
  if (!currentItems.length) {
    body.innerHTML = `<tr><td colspan="8">暂无样本</td></tr>`;
    return;
  }
  body.innerHTML = currentItems.map((item) => `
    <tr>
      <td>${item.index}</td>
      <td>${escapeHtml(item.data_source)}</td>
      <td>${escapeHtml(item.sample_id)}</td>
      <td>${escapeHtml(item.username)}</td>
      <td>${escapeHtml(item.created_at)}</td>
      <td class="sample-question-cell">${renderQuestion(item)}</td>
      <td>${statusCell(item)}</td>
      <td><a class="button secondary compact-button" href="${sampleDownload(item)}">下载</a></td>
    </tr>`).join("");
  for (const button of body.querySelectorAll(".sample-question-summary")) {
    button.addEventListener("click", () => {
      const item = currentItems.find((entry) => entry.sample_id === button.dataset.sample);
      if (item) openQuestionDialog(item);
    });
  }
}

function questionKey(value) {
  return String(value || "").replace(/(\d+)/g, (match) => match.padStart(8, "0"));
}

function openQuestionDialog(item) {
  const figures = (item.figures || [])
    .map((fig) => `<img src="/sample-asset/${encodeURIComponent(source)}/${encodeURIComponent(item.sample_id)}/${encodeURIComponent(fig)}" alt="">`)
    .join("");
  questionDialogTitle.textContent = `题目详情：${item.sample_id}`;
  questionDialogBody.innerHTML = `
    <section class="sample-detail-section">
      <h3>问题</h3>
      <div class="latex-preview">${mathContent(item.question || "未填写")}</div>
    </section>
    <section class="sample-detail-section">
      <h3>题图</h3>
      <div class="image-list">${figures || "<span>无题图</span>"}</div>
    </section>
    <section class="sample-detail-section">
      <h3>答案</h3>
      <div class="latex-preview">${answerMath(item.answer || "未填写")}</div>
    </section>`;
  questionDialog.hidden = false;
  typesetDialog();
}

function closeQuestionDialog() {
  questionDialog.hidden = true;
  questionDialogBody.innerHTML = "";
}

questionDialogClose.addEventListener("click", closeQuestionDialog);
questionDialog.addEventListener("click", (event) => {
  if (event.target === questionDialog) closeQuestionDialog();
});

load();
