const params = new URLSearchParams(window.location.search);
const jobId = params.get("job_id");
const readonly = params.get("readonly") === "1";
const preview = document.getElementById("preview");
const meta = document.getElementById("resultMeta");
const saveButton = document.getElementById("saveButton");
const completeButton = document.getElementById("completeButton");
const chatToggle = document.getElementById("chatToggle");
const chatPanel = document.getElementById("chatPanel");
const chatClose = document.getElementById("chatClose");
const chatMessages = document.getElementById("chatMessages");
const chatInput = document.getElementById("chatInput");
const chatImageInput = document.getElementById("chatImageInput");
const chatFiles = document.getElementById("chatFiles");
const chatSend = document.getElementById("chatSend");

const editableItems = [];
const replacementFiles = new Map();
let chatBusy = false;
const pendingTypeset = new Set();
let typesetTimer = null;
let typesetWaits = 0;
const questionTypes = ["", "单选题", "多选题", "判断题", "简答题", "自定义"];
const difficulties = ["", "简单", "中等", "困难"];

function isImagePath(line) {
  return /^(题图|答案)\/.+\.(jpe?g|png|webp|gif)$/i.test(line.trim());
}

function assetUrl(path) {
  return `/asset/${encodeURIComponent(jobId)}/${path.split("/").map(encodeURIComponent).join("/")}`;
}

function figureName(path) {
  const name = String(path || "").split("/").pop() || "";
  const stem = name.replace(/\.[^.]+$/, "");
  return { stem, filename: `${stem}.jpg` };
}

function questionWithFigureLinks(question, figures) {
  const figureMap = new Map();
  for (const figure of figures || []) {
    const item = figureName(figure);
    if (item.stem) {
      figureMap.set(item.stem, item.filename);
    }
  }
  if (!question || !figureMap.size) {
    return question;
  }
  return question.replace(/题图(?!\!)\s*([0-9]+(?:[-－—][0-9]+)?)\s*/g, (match, rawRef) => {
    const ref = rawRef.replace(/[－—]/g, "-");
    const filename = figureMap.get(ref);
    if (!filename) {
      return match;
    }
    return `题图![${ref}](${filename}) `;
  });
}

function splitBlocks(markdown) {
  return markdown
    .trim()
    .split(/\n(?=# 题目编号\n)/)
    .map((block) => block.trim())
    .filter(Boolean);
}

function parseBlock(block) {
  const lines = block.split(/\r?\n/);
  const data = {};
  let current = null;

  for (const line of lines) {
    const heading = line.match(/^#{1,2}\s+(.+)$/);
    if (heading) {
      current = heading[1].trim();
      data[current] = [];
      continue;
    }
    if (current) {
      data[current].push(line);
    }
  }

  const figures = (data["题图地址"] || []).map((line) => line.trim()).filter(Boolean);
  const question = (data["问题"] || []).join("\n").trim();

  return {
    id: (data["题目编号"] || []).join("\n").trim(),
    type: (data["题目类型"] || []).join("\n").trim(),
    difficulty: (data["题目难度"] || []).join("\n").trim(),
    question: questionWithFigureLinks(question, figures),
    figures,
    answer: (data["答案"] || []).join("\n").trim(),
    solution: (data["解答过程"] || []).join("\n").trim(),
    source: (data["题目来源"] || []).join("\n").trim(),
  };
}

function section(title) {
  const el = document.createElement("section");
  el.className = "preview-section";
  const heading = document.createElement("h2");
  heading.textContent = title;
  el.appendChild(heading);
  const body = document.createElement("div");
  body.className = "preview-body";
  el.appendChild(body);
  return [el, body];
}

function queueTypeset(element) {
  pendingTypeset.add(element);
  scheduleTypeset();
}

function scheduleTypeset() {
  if (typesetTimer) {
    return;
  }
  typesetTimer = window.setTimeout(flushTypeset, 80);
}

function flushTypeset() {
  typesetTimer = null;
  if (!window.MathJax?.typesetPromise) {
    typesetWaits += 1;
    if (typesetWaits < 120) {
      scheduleTypeset();
    }
    return;
  }
  typesetWaits = 0;
  const elements = Array.from(pendingTypeset).filter((element) => element.isConnected);
  pendingTypeset.clear();
  if (!elements.length) {
    return;
  }
  window.MathJax.typesetPromise(elements).catch(() => {});
}

function latexPreviewText(text, key) {
  const circled = ["", "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩", "⑪", "⑫", "⑬", "⑭", "⑮", "⑯", "⑰", "⑱", "⑲", "⑳"];
  const content = (text || "").replace(/\\textcircled\{(\d{1,2})\}/g, (_, value) => circled[Number(value)] || value);
  if (key !== "answer") {
    return content;
  }
  if (/\\\(|\\\[|\$/.test(content)) {
    return content;
  }
  if (!/[\\=]|\\dot|\\angle|\\frac|\\sqrt|\\Omega|\\varphi|\\Delta/.test(content)) {
    return content;
  }
  return content
    .split(/\r?\n/)
    .map((line) => {
      const trimmed = line.trim();
      return trimmed ? `\\(${trimmed}\\)` : "";
    })
    .join("\n");
}

function renderLatexEditor(body, item, key) {
  const previewLabel = document.createElement("div");
  previewLabel.className = "editor-label";
  previewLabel.textContent = "公式预览";

  const rendered = document.createElement("div");
  rendered.className = "latex-preview";

  const editLabel = document.createElement("div");
  editLabel.className = "editor-label";
  editLabel.textContent = "可编辑文本";

  const textarea = document.createElement("textarea");
  textarea.value = item[key] || "";
  textarea.rows = Math.min(14, Math.max(5, textarea.value.split(/\r?\n/).length + 2));

  const update = () => {
    rendered.textContent = latexPreviewText(item[key] || "", key);
    queueTypeset(rendered);
  };
  textarea.addEventListener("input", () => {
    item[key] = textarea.value;
    update();
  });

  body.appendChild(previewLabel);
  body.appendChild(rendered);
  body.appendChild(editLabel);
  body.appendChild(textarea);
  update();
}

function renderSelectWithCustom(body, item, key, options) {
  const wrapper = document.createElement("div");
  wrapper.className = "field-row";
  const select = document.createElement("select");
  for (const option of options) {
    const opt = document.createElement("option");
    opt.value = option;
    opt.textContent = option;
    select.appendChild(opt);
  }
  const custom = document.createElement("input");
  custom.type = "text";
  custom.placeholder = "自定义";

  if (options.includes(item[key])) {
    select.value = item[key];
    custom.hidden = true;
  } else if (item[key]) {
    select.value = "自定义";
    custom.value = item[key];
    custom.hidden = false;
  } else {
    select.value = "";
    custom.hidden = true;
  }

  select.addEventListener("change", () => {
    custom.hidden = select.value !== "自定义";
    item[key] = select.value === "自定义" ? custom.value : select.value;
  });
  custom.addEventListener("input", () => {
    item[key] = custom.value;
  });

  wrapper.appendChild(select);
  wrapper.appendChild(custom);
  body.appendChild(wrapper);
}

function renderTextInput(body, item, key) {
  const input = document.createElement("input");
  input.type = "text";
  input.value = item[key] || "";
  input.addEventListener("input", () => {
    item[key] = input.value;
  });
  body.appendChild(input);
}

function renderLabeledField(container, labelText, renderControl) {
  const label = document.createElement("label");
  label.className = "inline-field";
  const span = document.createElement("span");
  span.textContent = labelText;
  label.appendChild(span);
  renderControl(label);
  container.appendChild(label);
}

function renderMetaFields(body, item) {
  const grid = document.createElement("div");
  grid.className = "meta-grid";

  renderLabeledField(grid, "题目编号", (label) => {
    renderTextInput(label, item, "id");
  });
  renderLabeledField(grid, "题目类型", (label) => {
    renderSelectWithCustom(label, item, "type", questionTypes);
  });
  renderLabeledField(grid, "题目难度", (label) => {
    renderSelectWithCustom(label, item, "difficulty", difficulties);
  });
  renderLabeledField(grid, "题目来源", (label) => {
    renderTextInput(label, item, "source");
  });

  body.appendChild(grid);
}

function renderImageList(body, item, itemIndex) {
  const visibleLines = item.figures.length ? item.figures : [""];
  for (const [imageIndex, line] of visibleLines.entries()) {
    const row = document.createElement("div");
    row.className = "image-edit";

    if (line) {
      const figure = document.createElement("figure");
      const img = document.createElement("img");
      img.src = assetUrl(line);
      img.alt = line;
      img.loading = "lazy";
      figure.appendChild(img);
      row.appendChild(figure);
    }

    const controls = document.createElement("div");
    controls.className = "image-edit-controls";
    const path = document.createElement("span");
    path.textContent = line || "暂无图片";
    controls.appendChild(path);

    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.addEventListener("change", () => {
      const file = input.files?.[0];
      const key = `figure:${itemIndex}:${imageIndex}`;
      if (!file) {
        replacementFiles.delete(key);
        return;
      }
      replacementFiles.set(key, file);
      path.textContent = `${line || "新增图片"} -> ${file.name}`;
    });
    controls.appendChild(input);
    row.appendChild(controls);
    body.appendChild(row);
  }
}

function renderItem(item, itemIndex) {
  const card = document.createElement("article");
  card.className = "preview-card";

  let pair = section("基础信息");
  renderMetaFields(pair[1], item);
  card.appendChild(pair[0]);

  pair = section("问题");
  renderLatexEditor(pair[1], item, "question");
  card.appendChild(pair[0]);

  pair = section("题图");
  renderImageList(pair[1], item, itemIndex);
  card.appendChild(pair[0]);

  pair = section("答案");
  renderLatexEditor(pair[1], item, "answer");
  card.appendChild(pair[0]);

  return card;
}

function render(markdown) {
  preview.innerHTML = "";
  editableItems.length = 0;
  replacementFiles.clear();

  for (const block of splitBlocks(markdown)) {
    editableItems.push(parseBlock(block));
  }

  editableItems.forEach((item, itemIndex) => {
    preview.appendChild(renderItem(item, itemIndex));
  });

  meta.textContent = `共 ${editableItems.length} 道题，可编辑题型、难度、问题、答案、题图和来源`;
}

async function saveResult() {
  saveButton.disabled = true;
  meta.textContent = "正在保存校核结果并重新生成 zip...";
  try {
    const form = new FormData();
    form.append("job_id", jobId);
    form.append("payload", JSON.stringify({ items: editableItems }));
    for (const [key, file] of replacementFiles.entries()) {
      form.append(key, file);
    }

    const resp = await fetch("/api/save-result", {
      method: "POST",
      body: form,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(data.error || "保存失败");
    }

    replacementFiles.clear();
    meta.textContent = `保存完成：数据处理ID ${jobId}，共 ${data.question_count} 道题，题图 ${data.figure_count} 张，答案文本 ${data.answer_count} 条。尚未生成最终结果`;
    await reloadMarkdown();
  } finally {
    saveButton.disabled = false;
  }
}

async function reloadMarkdown() {
  const resp = await fetch(`/file/${encodeURIComponent(jobId)}/test_data.md?ts=${Date.now()}`);
  if (!resp.ok) {
    throw new Error("无法加载 test_data.md");
  }
  render(await resp.text());
}

async function main() {
  if (!jobId) {
    meta.textContent = "缺少 job_id";
    saveButton.disabled = true;
    completeButton.disabled = true;
    return;
  }

  if (readonly) {
    saveButton.hidden = true;
    completeButton.hidden = true;
    document.getElementById("chatAssistant").hidden = true;
  } else {
    saveButton.addEventListener("click", () => {
      saveResult().catch((err) => {
        meta.textContent = `错误：${err.message}`;
      });
    });
    completeButton.addEventListener("click", () => {
      completeReview().catch((err) => {
        meta.textContent = `错误：${err.message}`;
      });
    });
    bindChat();
  }
  await reloadMarkdown();
  if (!readonly) {
    saveButton.disabled = false;
    completeButton.disabled = false;
  }
}

async function completeReview() {
  completeButton.disabled = true;
  meta.textContent = "正在完成校核并生成最终结果...";
  try {
    const resp = await fetch("/api/complete-review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(formatError(data, "完成校核失败"));
    }
    meta.textContent = "完成校核成功，该数据处理ID已形成最终结果";
    notifyReviewCompleted();
    window.setTimeout(() => {
      window.close();
      meta.textContent = "完成校核成功。请关闭当前页面，数据处理页将自动刷新。";
    }, 300);
  } finally {
    completeButton.disabled = false;
  }
}

function notifyReviewCompleted() {
  const message = { type: "vl-data-gen-review-completed", job_id: jobId, at: Date.now() };
  try {
    window.opener?.postMessage(message, window.location.origin);
  } catch (err) {
    // Ignore cross-window notification failures; localStorage event is the fallback.
  }
  try {
    localStorage.setItem("vlDataGenReviewCompleted", JSON.stringify(message));
  } catch (err) {
    // Some browsers disable storage in private contexts.
  }
}

function bindChat() {
  chatToggle.addEventListener("click", () => {
    chatPanel.hidden = !chatPanel.hidden;
    if (!chatPanel.hidden) chatInput.focus();
  });
  chatClose.addEventListener("click", () => {
    chatPanel.hidden = true;
  });
  chatImageInput.addEventListener("change", renderChatFiles);
  chatSend.addEventListener("click", () => {
    sendChat().catch((err) => {
      const lastMessage = chatMessages.lastElementChild;
      if (lastMessage?.classList.contains("assistant")) {
        lastMessage.textContent = `错误：${err.message}`;
      } else {
        addChatMessage("assistant", `错误：${err.message}`);
      }
    });
  });
}

function renderChatFiles() {
  const files = Array.from(chatImageInput.files || []);
  chatFiles.textContent = files.length ? files.map((file) => file.name).join("、") : "";
}

function addChatMessage(role, text) {
  const item = document.createElement("div");
  item.className = `chat-message ${role}`;
  item.textContent = text;
  chatMessages.appendChild(item);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function sendChat() {
  if (chatBusy) return;
  const text = chatInput.value.trim();
  const files = Array.from(chatImageInput.files || []);
  if (!text && !files.length) {
    return;
  }
  chatBusy = true;
  chatSend.disabled = true;
  addChatMessage("user", text || `已上传 ${files.length} 张图片`);
  chatInput.value = "";
  chatImageInput.value = "";
  renderChatFiles();
  const waiting = "正在调用大模型...";
  addChatMessage("assistant", waiting);
  const lastMessage = chatMessages.lastElementChild;
  try {
    const form = new FormData();
    form.append("job_id", jobId);
    form.append("message", text);
    for (const file of files) {
      form.append("images", file);
    }
    const resp = await fetch("/api/job-chat", { method: "POST", body: form });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(formatError(data, "调用失败"));
    }
    lastMessage.textContent = data.answer || "模型未返回内容";
  } finally {
    chatBusy = false;
    chatSend.disabled = false;
  }
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

main().catch((err) => {
  meta.textContent = `错误：${err.message}`;
  saveButton.disabled = true;
  completeButton.disabled = true;
});
