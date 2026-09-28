import { apiGet, apiPost, apiUpload } from "./api.js";

const $ = (sel) => document.querySelector(sel);
const fileSelect = $("#file-select");
const fileUpload = $("#file-upload");
const uploadMsg = $("#upload-msg");
const instruction = $("#instruction");
const generateBtn = $("#generate");
const taskStatus = $("#task-status");
const historyEl = $("#history");
const resultEl = $("#result");

let currentTaskId = null;
let pollTimer = null;

init();

async function init() {
  await Promise.all([loadFiles(), loadHistory()]);
  const fromUrl = new URLSearchParams(location.search).get("task");
  if (fromUrl) await loadTask(fromUrl);
}

async function loadFiles() {
  try {
    const { files } = await apiGet("/api/v1/data-files");
    fileSelect.innerHTML = "";
    if (files.length === 0) {
      fileSelect.innerHTML = '<option value="">暂无文件，请上传</option>';
    } else {
      for (const f of files) {
        const opt = document.createElement("option");
        opt.value = f.name;
        opt.textContent = `${f.name}（${fmtSize(f.size)}）`;
        fileSelect.appendChild(opt);
      }
    }
    fileSelect.disabled = false;
    refreshGenerate();
  } catch (e) {
    fileSelect.innerHTML = '<option value="">加载失败</option>';
    fileSelect.disabled = false;
  }
}

async function loadHistory() {
  try {
    const { tasks } = await apiGet("/api/v1/tasks");
    historyEl.innerHTML = "";
    if (tasks.length === 0) {
      historyEl.innerHTML = '<li class="muted">暂无历史任务</li>';
      return;
    }
    for (const t of tasks.slice(0, 20)) {
      const li = document.createElement("li");
      li.innerHTML = `<span class="tag ${t.status}">${statusText(t.status)}</span>${escapeHtml(t.instruction)}`;
      li.addEventListener("click", () => loadTask(t.task_id));
      historyEl.appendChild(li);
    }
  } catch (e) {
    historyEl.innerHTML = '<li class="muted">历史加载失败</li>';
  }
}

fileUpload.addEventListener("change", async () => {
  const file = fileUpload.files[0];
  if (!file) return;
  uploadMsg.textContent = "上传中…";
  try {
    await apiUpload("/api/v1/upload", file);
    uploadMsg.textContent = `已上传 ${file.name}`;
    fileUpload.value = "";
    await loadFiles();
    fileSelect.value = file.name;
    refreshGenerate();
  } catch (e) {
    uploadMsg.textContent = e.message;
  }
});

fileSelect.addEventListener("change", refreshGenerate);

generateBtn.addEventListener("click", async () => {
  const file = fileSelect.value;
  const text = instruction.value.trim();
  if (!file || !text) return;
  setRunning(true);
  taskStatus.className = "status running";
  taskStatus.textContent = "正在生成…";
  try {
    const { task_id } = await apiPost("/api/v1/tasks", { file, instruction: text });
    currentTaskId = task_id;
    history.replaceState(null, "", `?task=${task_id}`);
    pollTask(task_id);
  } catch (e) {
    setRunning(false);
    taskStatus.className = "status failed";
    taskStatus.textContent = e.message;
  }
});

function pollTask(taskId) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const t = await apiGet(`/api/v1/tasks/${taskId}`);
      if (t.status === "done" || t.status === "failed") {
        clearInterval(pollTimer);
        setRunning(false);
        await renderTask(t);
        loadHistory();
      } else {
        taskStatus.textContent = "正在生成…";
      }
    } catch (e) {
      clearInterval(pollTimer);
      setRunning(false);
      taskStatus.className = "status failed";
      taskStatus.textContent = e.message;
    }
  }, 500);
}

async function loadTask(taskId) {
  currentTaskId = taskId;
  try {
    const t = await apiGet(`/api/v1/tasks/${taskId}`);
    if (t.status === "running" || t.status === "created") {
      setRunning(true);
      taskStatus.className = "status running";
      taskStatus.textContent = "正在生成…";
      pollTask(taskId);
    } else {
      setRunning(false);
      await renderTask(t);
    }
  } catch (e) {
    taskStatus.className = "status failed";
    taskStatus.textContent = e.message;
  }
}

async function renderTask(t) {
  if (t.status === "failed") {
    taskStatus.className = "status failed";
    taskStatus.textContent = "任务失败";
    resultEl.innerHTML = `<p class="muted">任务失败：${escapeHtml(JSON.stringify(t.result || {}))}</p>`;
    return;
  }
  taskStatus.className = "status success";
  taskStatus.textContent = "已完成";
  const outDir = t.result && t.result.output_dir;
  let html = "";
  try {
    const { report } = await apiGet(`/api/v1/tasks/${t.task_id}/report`);
    html += `<div class="report">${renderMarkdown(report)}</div>`;
  } catch (e) {
    html += `<p class="muted">报告加载失败</p>`;
  }

  const charts = ((t.result && t.result.deliverables) || []).filter((d) => d.startsWith("charts/"));
  if (charts.length) {
    html += '<div class="chart-grid">';
    for (const c of charts) {
      html += `<img src="/api/v1/tasks/${t.task_id}/files/${encodeURIComponent(c)}" alt="图表" />`;
    }
    html += "</div>";
  }

  const hasXlsx = ((t.result && t.result.deliverables) || []).includes("data_summary.xlsx");
  if (hasXlsx) {
    html += `<a class="download" href="/api/v1/tasks/${t.task_id}/files/data_summary.xlsx" download>下载汇总表 data_summary.xlsx</a>`;
  }
  resultEl.innerHTML = html || '<p class="muted">暂无结果</p>';
}

function setRunning(running) {
  generateBtn.disabled = running;
  generateBtn.textContent = running ? "生成中…" : "生成周报";
  fileSelect.disabled = running;
}

function refreshGenerate() {
  generateBtn.disabled = !fileSelect.value;
}

function statusText(s) {
  return { created: "待开始", running: "进行中", done: "完成", failed: "失败" }[s] || s;
}
function fmtSize(n) {
  return n > 1024 * 1024 ? (n / 1024 / 1024).toFixed(1) + "MB" : n > 1024 ? (n / 1024).toFixed(1) + "KB" : n + "B";
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function renderMarkdown(md) {
  const lines = escapeHtml(md).split("\n");
  let html = "";
  let list = null; // "ul" | "ol" | null
  const closeList = () => { if (list) { html += `</${list}>`; list = null; } };
  for (const line of lines) {
    if (/^# /.test(line)) { closeList(); html += `<h1>${line.slice(2)}</h1>`; }
    else if (/^## /.test(line)) { closeList(); html += `<h2>${line.slice(3)}</h2>`; }
    else if (/^### /.test(line)) { closeList(); html += `<h3>${line.slice(4)}</h3>`; }
    else if (/^- /.test(line)) { if (list !== "ul") { closeList(); html += "<ul>"; list = "ul"; } html += `<li>${line.slice(2)}</li>`; }
    else if (/^\d+\. /.test(line)) { if (list !== "ol") { closeList(); html += "<ol>"; list = "ol"; } html += `<li>${line.replace(/^\d+\. /, "")}</li>`; }
    else if (line.trim() === "") { closeList(); }
    else { closeList(); html += `<p>${line}</p>`; }
  }
  closeList();
  return html;
}
