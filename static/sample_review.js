const params = new URLSearchParams(window.location.search);
const source = params.get("source") || "";
const sample = params.get("sample") || "";
const meta = document.getElementById("reviewMeta");
const body = document.getElementById("reviewBody");
let record = null;
let figureFiles = [];
const pendingTypeset = new Set();
let typesetTimer = null;
let typesetWaits = 0;

function isApproved() {
  return record?.info?.["状态"] === "已审核";
}

function escapeHtml(text) {
  return String(text || "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

function asset(filename) {
  return `/sample-asset/${encodeURIComponent(source)}/${encodeURIComponent(sample)}/${encodeURIComponent(filename)}`;
}

function mathText(text) {
  const value = String(text || "").trim();
  if (!value) return "";
  if (/\\\(|\\\[|\$/.test(value)) return value;
  if (/[\\_^{}]/.test(value)) return `\\[${value}\\]`;
  return escapeHtml(value);
}

function answerMath(text) {
  const value = String(text || "").trim();
  if (!value) return "";
  if (/\\\(|\\\[|\$/.test(value)) return value;
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

function editor(title, id, value) {
  const preview = id === "answer" ? answerMath(value) : mathText(value);
  const readonly = isApproved() ? " readonly" : "";
  return `<section class="preview-section"><h2>${title}</h2><div class="preview-body"><strong>预览</strong><div class="latex-preview" id="${id}Preview">${preview}</div><textarea id="${id}"${readonly}>${escapeHtml(value)}</textarea></div></section>`;
}

function render() {
  const figures = (record.figures || []).map((fig) => `<img src="${asset(fig)}" alt="">`).join("");
  const uploadControl = isApproved() ? "" : `<label class="secondary-action file-action">上传图片<input id="figureUpload" type="file" accept="image/*" multiple></label><div id="figureUploadList"></div>`;
  body.innerHTML = `
    <article class="preview-card">
      ${editor("问题", "question", record.question)}
      <section class="preview-section">
        <h2>题图</h2>
        <div class="preview-body">
          <div class="image-list" id="figureList">${figures}</div>
          ${uploadControl}
        </div>
      </section>
      ${editor("答案", "answer", record.answer)}
    </article>`;
  for (const id of ["question", "answer"]) {
    document.getElementById(id).addEventListener("input", () => {
      document.getElementById(`${id}Preview`).innerHTML = id === "answer" ? answerMath(document.getElementById(id).value) : mathText(document.getElementById(id).value);
      queueTypeset(document.getElementById(`${id}Preview`));
    });
  }
  document.getElementById("figureUpload")?.addEventListener("change", (event) => {
    figureFiles = Array.from(event.target.files || []);
    document.getElementById("figureUploadList").textContent = figureFiles.map((file) => file.name).join("、");
  });
  document.getElementById("saveButton").disabled = isApproved();
  document.getElementById("completeButton").disabled = isApproved();
  document.getElementById("discardButton").disabled = isApproved();
  queueTypeset(body);
}

async function load() {
  const resp = await fetch(`/api/admin/sample-sources/${encodeURIComponent(source)}/samples/${encodeURIComponent(sample)}`);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || "加载失败");
  record = data;
  meta.textContent = `${data.source} / ${data.sample_id}${isApproved() ? " / 已审核，不可修改" : ""}`;
  render();
}

async function save() {
  if (isApproved()) throw new Error("已审核样本不能继续修改");
  const payload = { ...record, question: document.getElementById("question").value, answer: document.getElementById("answer").value };
  const form = new FormData();
  form.append("payload", JSON.stringify(payload));
  for (const file of figureFiles) {
    form.append("figure", file);
  }
  const resp = await fetch(`/api/admin/sample-sources/${encodeURIComponent(source)}/samples/${encodeURIComponent(sample)}/save`, {
    method: "POST",
    body: form,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || "保存失败");
  figureFiles = [];
  await load();
  meta.textContent = "保存完成";
}

async function setStatus(status, remark = "") {
  if (isApproved() && status !== "已审核") throw new Error("已审核样本不能继续修改");
  const resp = await fetch(`/api/admin/sample-sources/${encodeURIComponent(source)}/samples/${encodeURIComponent(sample)}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, remark }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || "状态保存失败");
  const message = { type: "vl-data-gen-sample-status-updated", source, sample, status, at: Date.now() };
  try {
    window.opener?.postMessage(message, window.location.origin);
  } catch (err) {
    // The storage event below is the fallback.
  }
  try {
    localStorage.setItem("vlDataGenSampleStatusUpdated", JSON.stringify(message));
  } catch (err) {
    // Storage can be disabled in private contexts.
  }
  window.close();
}

document.getElementById("saveButton").addEventListener("click", () => save().catch((err) => (meta.textContent = `错误：${err.message}`)));
document.getElementById("completeButton").addEventListener("click", () => save().then(() => setStatus("已审核")).catch((err) => (meta.textContent = `错误：${err.message}`)));
document.getElementById("discardButton").addEventListener("click", () => {
  const remark = window.prompt("请输入放弃原因", "") || "";
  setStatus("已放弃", remark).catch((err) => (meta.textContent = `错误：${err.message}`));
});

load().catch((err) => (meta.textContent = `错误：${err.message}`));
