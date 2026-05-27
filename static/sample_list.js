const params = new URLSearchParams(window.location.search);
const source = params.get("source") || "";
const body = document.getElementById("sampleListBody");
const meta = document.getElementById("sampleListMeta");
const downloadInfo = document.getElementById("downloadInfo");

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

function truncateChars(text, maxLength = 30) {
  const chars = Array.from(plainText(text));
  if (chars.length <= maxLength) return chars.join("");
  return `${chars.slice(0, maxLength).join("")}...`;
}

function renderQuestion(item) {
  return `<span class="sample-question-summary">${escapeHtml(truncateChars(item.question))}</span>`;
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
      <td>${statusCell(item)}</td>
      <td><a class="button secondary compact-button" href="${sampleDownload(item)}">下载</a></td>
    </tr>`).join("");
}

function questionKey(value) {
  return String(value || "").replace(/(\d+)/g, (match) => match.padStart(8, "0"));
}

load();
