import { apiGet, apiPost, apiUpload } from "./api.js";

const $ = (sel) => document.querySelector(sel);
const fileSelect = $("#file-select");
const fileUpload = $("#file-upload");
const uploadMsg = $("#upload-msg");
const btnInspect = $("#btn-inspect");
const btnWeek = $("#btn-week");
const btnGenerate = $("#btn-generate");
const btnRestart = $("#btn-restart");
const inspectResult = $("#inspect-result");
const weekResult = $("#week-result");
const taskStatus = $("#task-status");
const resultEl = $("#result");

const state = {
  file: null,
  inspect: null,
  mapping: {},
  amountMode: null,
  reportWeek: null,
  compareWeek: null,
  complete: { report: false, compare: false },
  currentTaskId: null,
  pollTimer: null,
};

init();

async function init() {
  await Promise.all([loadFiles(), loadMode()]);
}

async function loadMode() {
  try {
    const { model_provider } = await apiGet("/api/v1/health");
    $("#model-notice").hidden = model_provider !== "mock";
  } catch (e) {
    $("#model-notice").hidden = false;
  }
}

async function loadFiles() {
  try {
    const { files } = await apiGet("/api/v1/data-files");
    fileSelect.innerHTML = "";
    if (!files.length) {
      fileSelect.innerHTML = '<option value="">暂无文件，请上传</option>';
    } else {
      for (const f of files) {
        const opt = document.createElement("option");
        opt.value = f.name;
        opt.textContent = `${f.name}（${fmtSize(f.size)}）`;
        fileSelect.appendChild(opt);
      }
    }
  } catch (e) {
    fileSelect.innerHTML = '<option value="">加载失败</option>';
  }
  refreshStep1();
}

fileSelect.addEventListener("change", refreshStep1);
function refreshStep1() {
  btnInspect.disabled = !fileSelect.value;
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
    refreshStep1();
  } catch (e) {
    uploadMsg.textContent = e.message;
  }
});

btnInspect.addEventListener("click", async () => {
  if (!fileSelect.value) return;
  state.file = fileSelect.value;
  try {
    state.inspect = await apiPost("/api/v1/inspect", { file: state.file });
    state.mapping = { ...(state.inspect.mapping || {}) };
    state.amountMode = null;
    renderInspect();
    showStep(2);
  } catch (e) {
    uploadMsg.textContent = e.message;
  }
});

function renderInspect() {
  const ins = state.inspect;
  const cols = ins.summary.columns;
  let html = "";
  html += `<p>行数 <b>${ins.summary.rows}</b> · 列数 ${cols.length} · 大小 ${fmtSize(ins.summary.file_size)}</p>`;

  const q = ins.quality;
  if (q.sales) {
    html += `<p class="quality">销售额：有效 ${q.sales.valid} / 空 ${q.sales.empty} / 无法解析 ${q.sales.unparseable}</p>`;
  }
  if (q.date) {
    html += `<p class="quality">日期：有效 ${q.date.valid} / 空 ${q.date.empty} / 无法解析 ${q.date.unparseable}</p>`;
  }
  if (q.order_complete_rate !== undefined) {
    html += `<p class="quality">订单号完整率 ${(q.order_complete_rate * 100).toFixed(1)}% · 重复订单 ${q.duplicate_orders}</p>`;
  }

  const labels = { sales: "销售额列（必填）", date: "日期列", product: "商品列", channel: "渠道列", order: "订单号列" };
  html += '<div class="mapping">';
  for (const key of ["sales", "date", "product", "channel", "order"]) {
    const cur = state.mapping[key] || "";
    html += `<div class="field"><label>${labels[key]}</label><select data-key="${key}">`;
    html += key === "sales" ? "" : '<option value="">不指定</option>';
    for (const c of cols) {
      html += `<option value="${escapeAttr(c)}" ${c === cur ? "selected" : ""}>${escapeHtml(c)}</option>`;
    }
    html += "</select></div>";
  }
  html += "</div>";

  html += '<div class="field"><label>金额口径（F2）</label>';
  html += `<label class="radio"><input type="radio" name="amount" value="A" /> A 每行金额相加</label>`;
  html += `<label class="radio"><input type="radio" name="amount" value="B" /> B 整单金额去重（需完整订单号）</label>`;
  html += "</div>";

  if (ins.ambiguities && ins.ambiguities.length) {
    html += '<p class="warn">' + ins.ambiguities.map(escapeHtml).join("<br/>") + "</p>";
  }
  if (ins.pii_columns && ins.pii_columns.length) {
    html += `<p class="hint">以下列疑似个人信息，预览不显示原值：${ins.pii_columns.map(escapeHtml).join("、")}</p>`;
  }

  html += '<div id="blockers"></div>';
  inspectResult.innerHTML = html;

  inspectResult.querySelectorAll("select[data-key]").forEach((sel) => {
    sel.addEventListener("change", () => {
      const key = sel.dataset.key;
      state.mapping[key] = sel.value || undefined;
      if (key === "sales") delete state.mapping.sales;
      if (sel.value) state.mapping[key] = sel.value;
      else delete state.mapping[key];
      refreshBlockers();
    });
  });
  inspectResult.querySelectorAll('input[name="amount"]').forEach((r) => {
    r.addEventListener("change", () => {
      state.amountMode = r.value;
      refreshBlockers();
    });
  });
  refreshBlockers();
}

function remainingBlockers() {
  const b = [];
  if (!state.mapping.sales) b.push("缺少销售额列");
  if (!state.amountMode) b.push("金额口径未确认");
  const q = state.inspect.quality;
  if (q.sales && q.sales.unparseable > 0) b.push(`销售额列有 ${q.sales.unparseable} 个无法解析的值`);
  return b;
}

function refreshBlockers() {
  const b = remainingBlockers();
  const el = $("#blockers");
  if (el) {
    el.innerHTML = b.length
      ? '<p class="warn">待解决：' + b.map(escapeHtml).join("；") + "</p>"
      : '<p class="ok">可以继续。</p>';
  }
  btnWeek.disabled = b.length > 0;
}

btnWeek.addEventListener("click", () => {
  if (state.inspect.has_date) {
    renderWeek();
    showStep(3);
  } else {
    state.reportWeek = null;
    state.compareWeek = null;
    state.complete = { report: false, compare: false };
    startGenerate();
  }
});

function renderWeek() {
  const weeks = state.inspect.weeks || [];
  if (!weeks.length) {
    // 无有效日期 → 汇总模式
    state.reportWeek = null;
    weekResult.innerHTML = '<p class="hint">未识别到有效日期，将生成"销售数据汇总"（不含周环比）。</p>';
    return;
  }
  const latest = weeks[weeks.length - 1];
  state.reportWeek = state.reportWeek || latest;
  state.compareWeek = prevWeek(state.reportWeek);
  let html = `<div class="field"><label>报告周（周一）</label><select id="week-select">`;
  for (const w of weeks) {
    html += `<option value="${w}" ${w === state.reportWeek ? "selected" : ""}>${w} ~ ${weekEnd(w)}</option>`;
  }
  html += "</select></div>";
  html += `<p class="hint">对比周（固定为上一自然周）：${state.compareWeek} ~ ${weekEnd(state.compareWeek)}</p>`;
  html += `<label class="check"><input type="checkbox" id="ck-report" /> 报告周数据完整</label>`;
  html += `<label class="check"><input type="checkbox" id="ck-compare" /> 对比周数据完整</label>`;
  html += '<p class="hint">只有两周都确认完整，才会计算环比。</p>';
  weekResult.innerHTML = html;

  $("#week-select").addEventListener("change", (e) => {
    state.reportWeek = e.target.value;
    state.compareWeek = prevWeek(state.reportWeek);
    renderWeek();
  });
  $("#ck-report").addEventListener("change", (e) => (state.complete.report = e.target.checked));
  $("#ck-compare").addEventListener("change", (e) => (state.complete.compare = e.target.checked));
}

function parseLocal(s) {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}
function fmtLocal(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function prevWeek(mondayStr) {
  const d = parseLocal(mondayStr);
  d.setDate(d.getDate() - 7);
  return fmtLocal(d);
}
function weekEnd(mondayStr) {
  const d = parseLocal(mondayStr);
  d.setDate(d.getDate() + 6);
  return fmtLocal(d);
}

btnGenerate.addEventListener("click", startGenerate);

async function startGenerate() {
  showStep(4);
  taskStatus.className = "status running";
  taskStatus.textContent = "正在生成…";
  try {
    const body = {
      file: state.file,
      instruction: "做成销售周报",
      field_mapping: state.mapping,
      amount_mode: state.amountMode || "A",
      report_week: state.reportWeek,
      compare_week: state.compareWeek,
      complete: state.complete,
    };
    const { task_id } = await apiPost("/api/v1/tasks", body);
    state.currentTaskId = task_id;
    pollTask(task_id);
  } catch (e) {
    taskStatus.className = "status failed";
    taskStatus.textContent = e.message;
  }
}

function pollTask(taskId) {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    try {
      const t = await apiGet(`/api/v1/tasks/${taskId}`);
      if (t.status === "done" || t.status === "failed") {
        clearInterval(state.pollTimer);
        await renderResult(t);
      } else {
        taskStatus.textContent = "正在生成…";
      }
    } catch (e) {
      clearInterval(state.pollTimer);
      taskStatus.className = "status failed";
      taskStatus.textContent = e.message;
    }
  }, 500);
}

async function renderResult(t) {
  if (t.status === "failed") {
    taskStatus.className = "status failed";
    taskStatus.textContent = "任务失败：" + (t.error?.message || "请重试");
    resultEl.innerHTML = "";
    return;
  }
  taskStatus.className = "status success";
  taskStatus.textContent = "已完成";

  let html = "";
  try {
    const { facts, change_facts } = await apiGet(`/api/v1/tasks/${t.task_id}/facts`);
    html += '<div class="facts">';
    for (const f of facts) {
      html += `<div class="fact"><b>${escapeHtml(f.label)}</b><span class="fact-val">${escapeHtml(fmtValue(f.value))}${f.unit ? " " + escapeHtml(f.unit) : ""}</span><span class="fact-src">来源 ${escapeHtml(f.source_col || "—")} · ${escapeHtml(f.formula || "")}${f.verified ? " · 已核对" : ""}</span></div>`;
    }
    html += "</div>";
    if (change_facts && change_facts.length) {
      html += '<div class="changes">';
      for (const c of change_facts) {
        html += `<p>${escapeHtml(c.name)}：${c.direction} ${escapeHtml(String(c.delta))}${c.contribution_pct != null ? `，占总变化 ${c.contribution_pct}%` : ""}</p>`;
      }
      html += "</div>";
    }
  } catch (e) {
    html += '<p class="muted">依据加载失败</p>';
  }

  try {
    const { report } = await apiGet(`/api/v1/tasks/${t.task_id}/report`);
    html += `<div class="report">${renderMarkdown(report)}</div>`;
  } catch (e) {
    html += '<p class="muted">报告加载失败</p>';
  }

  const charts = ((t.result && t.result.deliverables) || []).filter((d) => d.startsWith("charts/"));
  if (charts.length) {
    html += '<div class="chart-grid">';
    for (const c of charts) {
      html += `<div class="chart-item"><img src="/api/v1/tasks/${t.task_id}/files/${encodeURIComponent(c)}" alt="图表 ${c}" data-name="${c}" /></div>`;
    }
    html += "</div>";
  }

  const hasXlsx = ((t.result && t.result.deliverables) || []).includes("data_summary.xlsx");
  if (hasXlsx) {
    html += `<a class="download" href="/api/v1/tasks/${t.task_id}/files/data_summary.xlsx" download>下载汇总表</a>`;
  }
  html += ` <a class="download" href="/api/v1/tasks/${t.task_id}/files/analysis_basis.json" download>下载依据文件</a>`;

  resultEl.innerHTML = html || '<p class="muted">暂无结果</p>';
  resultEl.querySelectorAll("img").forEach((img) => {
    img.addEventListener("error", () => {
      const holder = img.closest(".chart-item");
      if (holder) holder.innerHTML = `<p class="muted">图片加载失败：${escapeHtml(img.dataset.name || "")}</p>`;
    });
  });
}

btnRestart.addEventListener("click", () => {
  clearInterval(state.pollTimer);
  state.currentTaskId = null;
  state.inspect = null;
  state.amountMode = null;
  state.reportWeek = null;
  state.complete = { report: false, compare: false };
  resultEl.innerHTML = '<p class="muted">生成后在这里查看周报、图表与依据。</p>';
  showStep(1);
});

function showStep(n) {
  for (let i = 1; i <= 4; i++) {
    document.getElementById(`step-${i}`).hidden = i !== n;
    document.querySelector(`.step[data-step="${i}"]`).classList.toggle("active", i === n);
  }
}

function fmtValue(v) {
  if (v == null) return "待确认";
  if (typeof v === "object") return JSON.stringify(v);
  return v;
}
function fmtSize(n) {
  return n > 1024 * 1024 ? (n / 1024 / 1024).toFixed(1) + "MB" : n > 1024 ? (n / 1024).toFixed(1) + "KB" : n + "B";
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function escapeAttr(s) {
  return String(s).replace(/"/g, "&quot;").replace(/</g, "&lt;");
}
function renderMarkdown(md) {
  const lines = escapeHtml(md).split("\n");
  let html = "";
  let list = null;
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
