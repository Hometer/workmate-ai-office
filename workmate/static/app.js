import { apiGet, apiPost, apiUpload } from "./api.js?v=0.8-workspace1";
import { formatChangeFact } from "./formatters.js?v=0.8-workspace1";
import { fileName, filterTasks, summaryIdentity, reportSection, shareWidth, taskProgress } from "./workspace.js?v=0.8-workspace1";

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
const emptyResult = resultEl.innerHTML;

const state = {
  file: null,
  inspect: null,
  inspectPending: false,
  inspectError: null,
  inspectVersion: 0,
  mapping: {},
  amountMode: null,
  unit: null,
  reportWeek: null,
  compareWeek: null,
  complete: { report: false, compare: false },
  currentTaskId: null,
  pollTimer: null,
  view: "home",
  step: 1,
  tasks: [],
  files: [],
  filter: "all",
  requestVersion: 0,
  submitting: false,
  historyVersion: 0,
  filesVersion: 0,
  uploadPending: false,
};

showStep(1);

async function init() {
  restoreLocation();
  await Promise.all([loadFiles(), loadMode(), loadHistory(), loadDiagnostics()]);
}

const views = { home: "工作台", files: "数据文件", library: "历史成果", settings: "环境自检", report: "销售周报" };
function updateUrl(tab, push = false) {
  const url = new URL(location.href);
  url.search = "";
  if (state.view === "report" && state.currentTaskId) {
    url.searchParams.set("task", state.currentTaskId);
    if (tab && tab !== "overview") url.searchParams.set("tab", tab);
  } else if (state.view !== "home") url.searchParams.set("view", state.view);
  window.history[push ? "pushState" : "replaceState"](null, "", url);
}

function navigate(view, writeUrl = true) {
  if (!views[view]) view = "home";
  const changed = state.view !== view;
  state.view = view;
  document.querySelectorAll(".workspace-view").forEach((el) => (el.hidden = el.id !== `view-${view}`));
  document.querySelectorAll("[data-view]").forEach((el) => {
    const selected = el.dataset.view === view || (el.dataset.view === "library" && view === "report");
    el.classList.toggle("active", selected);
    if (el.classList.contains("nav-item") && selected) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
  $("#breadcrumb").textContent = views[view];
  if (writeUrl) updateUrl(undefined, changed);
  if (changed) window.scrollTo(0, 0);
}

function restoreLocation() {
  const params = new URLSearchParams(location.search);
  const id = params.get("task");
  if (id) viewTask(id, true);
  else navigate(params.get("view") || "home", false);
}
window.addEventListener("popstate", restoreLocation);
$(".brand").addEventListener("click", (event) => {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault(); navigate("home");
});
document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.view)));
document.querySelectorAll('[data-action="new"]').forEach((button) => button.addEventListener("click", newReport));
document.querySelectorAll('[data-action="upload"]').forEach((button) => button.addEventListener("click", () => {
  newReport(); fileUpload.click();
}));
document.querySelectorAll("[data-step-back]").forEach((button) => button.addEventListener("click", () => {
  showStep(Number(button.dataset.stepBack));
}));
$("#btn-refresh-files").addEventListener("click", loadFiles);
$("#btn-refresh-history").addEventListener("click", loadHistory);
$("#history-search").addEventListener("input", renderLibrary);
document.querySelectorAll("[data-filter]").forEach((button) => button.addEventListener("click", () => {
  state.filter = button.dataset.filter;
  document.querySelectorAll("[data-filter]").forEach((el) => {
    el.classList.toggle("active", el === button);
    el.setAttribute("aria-pressed", String(el === button));
  });
  renderLibrary();
}));

async function loadMode() {
  try {
    const { model_provider } = await apiGet("/api/v1/health");
    setModelNotice(model_provider);
  } catch (e) {
    setModelNotice(null);
  }
}

function setModelNotice(mode) {
  const notice = $("#model-notice");
  notice.hidden = mode != null && mode !== "mock";
  notice.textContent = mode == null ? "暂时无法确认本地模型状态，请先检查服务环境。" : "当前新任务为演示模式：未调用真实模型。历史任务以各自的总结身份为准。";
}

$("#btn-diagnostics").addEventListener("click", loadDiagnostics);
async function loadDiagnostics() {
  const button = $("#btn-diagnostics");
  button.disabled = true;
  $("#environment-state").textContent = "检查中…";
  try {
    const data = await apiGet("/api/v1/diagnostics");
    $("#environment-state").textContent = data.status === "ready" ? "本地环境可用" : "有待处理项";
    $("#environment-checks").innerHTML = data.checks.map((check) => `<li><strong>${escapeHtml(check.message)}</strong>${check.steps.length ? `<ol>${check.steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol>` : ""}</li>`).join("");
    setModelNotice(data.model_mode);
  } catch (e) {
    $("#environment-state").textContent = "环境检查失败";
    $("#environment-checks").innerHTML = `<li>${escapeHtml(e.message)}；请确认 WorkMate 正在运行后重新检查。</li>`;
  } finally {
    button.disabled = false;
  }
}

async function loadHistory() {
  const version = ++state.historyVersion;
  $("#btn-refresh-history").disabled = true;
  try {
    const { tasks } = await apiGet("/api/v1/tasks");
    if (version !== state.historyVersion) return;
    state.tasks = tasks;
    const el = $("#history");
    el.innerHTML = "";
    if (!tasks.length) {
      el.innerHTML = '<li class="empty-history">还没有生成记录</li>';
    }
    for (const t of tasks.slice(0, 8)) {
      const li = document.createElement("li");
      li.dataset.taskId = t.task_id;
      const button = document.createElement("button");
      button.type = "button";
      const name = fileName(t.input_file);
      const created = new Date(t.created_at);
      const dateLabel = Number.isNaN(created.getTime()) ? "" : created.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
      button.innerHTML = `<span class="history-name">${escapeHtml(name)}</span><span class="history-top"><span class="tag ${safeStatus(t.status)}">${statusText(t.status)}</span><small>${escapeHtml(dateLabel)}</small></span>`;
      button.setAttribute("aria-label", `${statusText(t.status)}：${name}${dateLabel ? "，" + dateLabel : ""}`);
      button.classList.toggle("active", t.task_id === state.currentTaskId);
      button.addEventListener("click", () => viewTask(t.task_id));
      li.appendChild(button);
      el.appendChild(li);
    }
    renderLibrary();
    $("#recent-tasks").innerHTML = tasks.length ? tasks.slice(0, 3).map((t) => `<button class="task-card" data-task="${escapeAttr(t.task_id)}"><span class="task-card-top"><span class="document-icon">${icon("file")}</span>${statusPill(t.status)}</span><strong>${escapeHtml(fileName(t.input_file))}</strong><small>${escapeHtml(taskDate(t.created_at))}</small></button>`).join("") : '<div class="list-empty">还没有生成记录<p>从上方选择数据，开始第一份周报。</p></div>';
    bindTasks($("#recent-tasks"));
  } catch (e) {
    if (version !== state.historyVersion) return;
    $("#history").innerHTML = '<li class="empty-history">历史加载失败</li>';
    $("#recent-tasks").innerHTML = '<p class="section-load-error">最近任务加载失败，请到历史成果中刷新重试。</p>';
    $("#library-list").innerHTML = '<p class="section-load-error">历史任务加载失败，请点击刷新重试。</p>';
    $("#library-count").textContent = "加载失败";
  } finally {
    if (version === state.historyVersion) $("#btn-refresh-history").disabled = false;
  }
}

function icon(name) { return `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`; }
function safeStatus(s) { return ["created", "running", "done", "failed"].includes(s) ? s : "unknown"; }
function statusPill(s) { return `<span class="status-pill ${safeStatus(s)}">${escapeHtml(statusText(s))}</span>`; }
function taskDate(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? "日期未记录" : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }); }
function bindTasks(el) { el.querySelectorAll("[data-task]").forEach((b) => b.addEventListener("click", () => viewTask(b.dataset.task))); }
function renderLibrary() {
  const tasks = filterTasks(state.tasks, $("#history-search").value, state.filter);
  $("#library-count").textContent = `共 ${state.tasks.length} 个任务 · 当前显示 ${tasks.length} 个`;
  $("#library-list").innerHTML = tasks.length ? tasks.map((t) => `<button class="library-row" data-task="${escapeAttr(t.task_id)}"><span class="document-icon">${icon("file")}</span><div><strong>${escapeHtml(fileName(t.input_file))}</strong><small>${escapeHtml(taskDate(t.created_at))} · ${t.status === "done" ? "报告与数据成果" : "任务记录"}</small></div>${statusPill(t.status)}${icon("arrow")}</button>`).join("") : '<div class="list-empty">没有匹配的任务<p>调整文件名或状态筛选后再试。</p></div>';
  bindTasks($("#library-list"));
}

async function viewTask(taskId, fromLocation = false) {
  clearTimeout(state.pollTimer);
  const version = ++state.requestVersion;
  const changed = state.currentTaskId !== taskId || state.view !== "report";
  const tab = fromLocation || state.currentTaskId === taskId ? new URLSearchParams(location.search).get("tab") : "overview";
  state.currentTaskId = taskId;
  navigate("report", false);
  updateUrl(tab, !fromLocation && changed);
  document.querySelectorAll("#history button").forEach((button) => button.classList.remove("active"));
  const selected = [...document.querySelectorAll("#history button")].find((button) => button.parentElement?.dataset.taskId === taskId);
  if (selected) selected.classList.add("active");
  setResultState("running", "正在读取");
  resultEl.innerHTML = '<div class="result-pending"><span class="pending-spinner" aria-hidden="true"></span><strong>正在读取周报</strong><p>请稍候，正在获取保存的结果。</p></div>';
  try {
    const t = await apiGet(`/api/v1/tasks/${taskId}`);
    if (version !== state.requestVersion || taskId !== state.currentTaskId) return;
    if (t.status === "running" || t.status === "created") {
      state.currentTaskId = taskId;
      taskStatus.className = "status running";
      taskStatus.textContent = "正在生成…";
      setResultState("running", "生成中");
      pollTask(taskId);
      return;
    }
    await renderResult(t, version, tab);
  } catch (e) {
    if (version !== state.requestVersion) return;
    resultEl.innerHTML = errorPanel("暂时无法读取这份成果", e.message, taskId);
    bindResultActions();
    setResultState("failed", "读取失败");
  }
}

function renderSummary(basis) {
  const mapping = basis.field_mapping || {};
  const unit = basis.unit || "单位待确认";
  const scope = basis.report_week ? `报告周 ${basis.report_week} ~ ${weekEnd(basis.report_week)}` : "全表";
  let html = '<div class="basis-summary">';
  html += `<p><b>统计范围：</b>${escapeHtml(scope)}</p>`;
  html += `<p><b>销售额列：</b>${escapeHtml(mapping.sales || "—")} · <b>金额口径：</b>${basis.amount_mode === "B" ? "B 整单金额去重" : "A 每行金额相加"}</p>`;
  html += `<p><b>金额单位：</b>${escapeHtml(unit)}</p>`;
  if (basis.compare_week) {
    html += `<p><b>对比周：</b>${escapeHtml(basis.compare_week)}${basis.compare_empty ? "（无记录）" : ""}</p>`;
  }
  if (basis.compare_unavailable_reason) {
    html += `<p class="warn">${escapeHtml(basis.compare_unavailable_reason)}</p>`;
  }
  html += `<p><b>数字核对：</b>${basis.verify?.passed ? "本次计算结果已核对；业务完整性需人工确认" : "历史任务未记录核对状态"}</p>`;
  html += `<p><b>单位确认：</b>${basis.unit_status === "confirmed" ? "已确认" : basis.unit_status === "pending" ? "待确认" : "历史任务未记录"}</p>`;
  if (basis.report_week) {
    const complete = basis.completeness || {};
    html += `<p><b>人工完整性：</b>报告周${complete.report ? "已确认" : "未确认"}，对比周${complete.compare ? "已确认" : "未确认"}</p>`;
  }
  const validation = basis.summary_validation;
  const identity = `${summaryIdentity(validation).label}；业务质量需人工核对`;
  html += `<p><b>总结身份：</b>${escapeHtml(identity)}</p>`;
  html += "</div>";
  return html;
}

function statusText(s) {
  return { created: "待开始", running: "进行中", done: "已完成", failed: "未成功" }[s] || "状态待确认";
}

async function loadFiles() {
  const version = ++state.filesVersion;
  const selected = fileSelect.value;
  $("#btn-refresh-files").disabled = true;
  try {
    const { files } = await apiGet("/api/v1/data-files");
    if (version !== state.filesVersion) return;
    state.files = files;
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
    if (files.some((file) => file.name === selected)) fileSelect.value = selected;
    $("#file-count").textContent = String(files.length);
    $("#files-description").textContent = `${files.length} 份数据文件 · CSV / Excel`;
    $("#files-list").innerHTML = files.length ? files.map((file) => `<button class="file-row" data-file="${escapeAttr(file.name)}"><span class="document-icon">${icon("folder")}</span><div><strong>${escapeHtml(file.name)}</strong><small>${escapeHtml(fmtSize(file.size))} · ${file.name.toLowerCase().endsWith(".xlsx") ? "Excel 表格" : "CSV 表格"} · 点击检查数据</small></div>${icon("arrow")}</button>`).join("") : '<div class="list-empty">这里还没有数据文件<p>点击右上角上传，添加第一份销售表。</p></div>';
    $("#files-list").querySelectorAll("[data-file]").forEach((button) => button.addEventListener("click", () => {
      if (state.submitting || state.uploadPending) return;
      newReport(); fileSelect.value = button.dataset.file; refreshStep1(); btnInspect.click();
    }));
  } catch (e) {
    if (version !== state.filesVersion) return;
    fileSelect.innerHTML = '<option value="">加载失败</option>';
    $("#files-description").textContent = "文件加载失败";
    $("#files-list").innerHTML = '<p class="section-load-error">数据文件加载失败，请点击刷新列表重试。</p>';
  } finally {
    if (version === state.filesVersion) $("#btn-refresh-files").disabled = false;
  }
  refreshStep1();
}

fileSelect.addEventListener("change", refreshStep1);
function refreshStep1() {
  btnInspect.disabled = !fileSelect.value || state.inspectPending || state.uploadPending || state.submitting;
}

fileUpload.addEventListener("change", async () => {
  const file = fileUpload.files[0];
  if (!file) return;
  state.uploadPending = true;
  fileUpload.disabled = true;
  fileSelect.disabled = true;
  refreshStep1();
  $(".upload-box").setAttribute("aria-busy", "true");
  const selected = fileSelect.value;
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
    fileSelect.value = selected;
  } finally {
    state.uploadPending = false;
    fileUpload.disabled = false;
    fileSelect.disabled = false;
    $(".upload-box").removeAttribute("aria-busy");
    refreshStep1();
  }
});

btnInspect.addEventListener("click", async () => {
  if (!fileSelect.value) return;
  btnInspect.disabled = true;
  btnInspect.textContent = "正在检查数据…";
  if (state.file !== fileSelect.value) {
    state.unit = null;
    state.reportWeek = null;
    state.compareWeek = null;
    state.complete = { report: false, compare: false };
  }
  state.file = fileSelect.value;
  const version = ++state.inspectVersion;
  state.inspectPending = true;
  fileSelect.disabled = true;
  fileUpload.disabled = true;
  state.inspectError = null;
  try {
    const inspected = await apiPost("/api/v1/inspect", { file: state.file });
    if (version !== state.inspectVersion) return;
    state.inspectPending = false;
    acceptInspection(inspected);
    state.amountMode = null;
    renderInspect();
    showStep(2);
  } catch (e) {
    if (version === state.inspectVersion) uploadMsg.textContent = e.message;
  } finally {
    if (version === state.inspectVersion) {
      state.inspectPending = false;
      fileSelect.disabled = false;
      fileUpload.disabled = false;
      btnInspect.innerHTML = `检查数据并继续${icon("arrow")}`;
      refreshStep1();
    }
  }
});

function renderInspect() {
  const ins = state.inspect;
  const cols = ins.summary.columns;
  let html = "";
  html += `<p><strong class="selected-file-name">${escapeHtml(state.file)}</strong><span>行数 <b>${ins.summary.rows}</b> · 列数 ${cols.length} · 大小 ${fmtSize(ins.summary.file_size)}</span></p>`;

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
    html += `<div class="field"><label for="mapping-${key}">${labels[key]}</label><select id="mapping-${key}" data-key="${key}">`;
    html += key === "sales" ? "" : '<option value="">不指定</option>';
    for (const c of cols) {
      html += `<option value="${escapeAttr(c)}" ${c === cur ? "selected" : ""}>${escapeHtml(c)}</option>`;
    }
    html += "</select></div>";
  }
  html += "</div>";

  html += '<div class="field"><label>金额口径 · 请选择数据的实际含义</label>';
  html += `<label class="radio"><input type="radio" name="amount" value="A" ${state.amountMode === "A" ? "checked" : ""} /> A 每行金额相加</label>`;
  html += `<label class="radio"><input type="radio" name="amount" value="B" ${state.amountMode === "B" ? "checked" : ""} /> B 整单金额去重（需完整订单号）</label>`;
  html += "</div>";

  html += '<div class="field"><label for="unit-input">金额单位（留空为待确认）</label><input type="text" id="unit-input" placeholder="如 元 / USD" /></div>';

  if (ins.ambiguities && ins.ambiguities.length) {
    html += '<p class="warn">' + ins.ambiguities.map(escapeHtml).join("<br/>") + "</p>";
  }
  if (ins.pii_columns && ins.pii_columns.length) {
    html += `<p class="hint">以下列疑似个人信息，预览不显示原值：${ins.pii_columns.map(escapeHtml).join("、")}</p>`;
  }

  html += '<div id="blockers"></div>';
  inspectResult.innerHTML = html;

  const unitInput = $("#unit-input");
  unitInput.value = state.unit || ins.currency?.unit || "";
  unitInput.addEventListener("input", () => (state.unit = unitInput.value.trim() || null));

  inspectResult.querySelectorAll("select[data-key]").forEach((sel) => {
    sel.addEventListener("change", () => {
      const key = sel.dataset.key;
      const prevDate = state.mapping.date;
      if (sel.value) state.mapping[key] = sel.value;
      else delete state.mapping[key];
      if (key === "date" && prevDate !== state.mapping.date) {
        state.reportWeek = null;
        state.complete = { report: false, compare: false };
      }
      reInspect();
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

function acceptInspection(inspected) {
  const previous = state.inspect?.summary?.fingerprint;
  if (previous && previous !== inspected.summary?.fingerprint) {
    state.unit = null;
    state.reportWeek = null;
    state.compareWeek = null;
    state.complete = { report: false, compare: false };
  }
  state.inspect = inspected;
  state.mapping = { ...(inspected.mapping || {}) };
}

async function reInspect() {
  const version = ++state.inspectVersion;
  state.inspectPending = true;
  state.inspectError = null;
  refreshBlockers();
  try {
    const res = await apiPost("/api/v1/inspect", { file: state.file, field_mapping: { ...state.mapping } });
    if (version !== state.inspectVersion) return;
    state.inspectPending = false;
    acceptInspection(res);
    renderInspect();
  } catch (e) {
    if (version !== state.inspectVersion) return;
    state.inspectPending = false;
    state.inspectError = e.message;
    refreshBlockers();
  }
}

function remainingBlockers() {
  const b = [];
  if (state.inspectPending) b.push("正在重新检查字段，请稍候");
  if (state.inspectError) b.push(`字段检查失败：${state.inspectError} 请重新选择有效字段后继续。`);
  if (!state.mapping.sales) b.push("缺少销售额列");
  if (!state.amountMode) b.push("金额口径未确认");
  const q = state.inspect.quality;
  if (q.sales && q.sales.empty > 0) b.push(`销售额列有 ${q.sales.empty} 个空值`);
  if (q.sales && q.sales.unparseable > 0) b.push(`销售额列有 ${q.sales.unparseable} 个无法解析的值`);
  if (state.amountMode === "B" && q.order_complete_rate !== 1) b.push("整单金额去重需要完整订单号，请检查订单号列或使用每行金额口径");
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
  btnWeek.innerHTML = state.inspect.has_date ? `继续选择周次${icon("arrow")}` : `生成销售数据汇总${icon("spark")}`;
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
    state.reportWeek = null;
    weekResult.innerHTML = '<p class="hint">未识别到有效日期，将生成"销售数据汇总"（不含周环比）。</p>';
    return;
  }
  const latest = weeks[weeks.length - 1];
  state.reportWeek = state.reportWeek || latest;
  state.compareWeek = prevWeek(state.reportWeek);
  const stats = state.inspect.week_stats || [];
  const statOf = (monday) => stats.find((s) => s.monday === monday);

  let html = `<div class="field"><label for="week-select">报告周（周一至周日）</label><select id="week-select">`;
  for (const w of weeks) {
    html += `<option value="${w}" ${w === state.reportWeek ? "selected" : ""}>${w} ~ ${weekEnd(w)}</option>`;
  }
  html += "</select></div>";

  const r = statOf(state.reportWeek);
  const c = statOf(state.compareWeek);
  html += `<p class="quality">报告周：有效行 ${r ? r.valid_rows : 0}，有记录天数 ${r ? r.days_with_data : 0}</p>`;
  html += `<p class="quality">对比周（上一自然周 ${state.compareWeek} ~ ${weekEnd(state.compareWeek)}）：有效行 ${c ? c.valid_rows : 0}，有记录天数 ${c ? c.days_with_data : 0}</p>`;

  html += `<label class="check"><input type="checkbox" id="ck-report" ${state.complete.report ? "checked" : ""} /> 报告周数据完整</label>`;
  html += `<label class="check"><input type="checkbox" id="ck-compare" ${state.complete.compare ? "checked" : ""} /> 对比周数据完整</label>`;
  html += '<p class="hint">只有两周都确认完整，才会计算环比。</p>';
  weekResult.innerHTML = html;

  $("#week-select").addEventListener("change", (e) => {
    state.reportWeek = e.target.value;
    state.compareWeek = prevWeek(state.reportWeek);
    state.complete = { report: false, compare: false }; // 切周清空完整性确认
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
  if (state.submitting) return;
  state.submitting = true;
  document.querySelectorAll("[data-action]").forEach((button) => (button.disabled = true));
  btnGenerate.disabled = true;
  btnWeek.disabled = true;
  const version = ++state.requestVersion;
  state.currentTaskId = null;
  showStep(4);
  navigate("report");
  taskStatus.className = "status running";
  taskStatus.textContent = "正在生成…";
  setResultState("running", "生成中");
  resultEl.innerHTML = '<div class="result-pending"><span class="pending-spinner" aria-hidden="true"></span><strong>正在整理周报</strong><p>生成结束后，销售摘要和图表会出现在这里。</p></div>';
  try {
    const body = {
      file: state.file,
      instruction: "做成销售周报",
      field_mapping: state.mapping,
      amount_mode: state.amountMode || "A",
      report_week: state.reportWeek,
      compare_week: state.compareWeek,
      complete: state.complete,
      unit: state.unit,
      confirmation_id: state.inspect?.confirmation_id,
    };
    const { task_id } = await apiPost("/api/v1/tasks", body);
    loadHistory();
    if (version !== state.requestVersion) return;
    state.currentTaskId = task_id;
    if (state.view === "report") updateUrl();
    pollTask(task_id);
  } catch (e) {
    if (version !== state.requestVersion) return;
    taskStatus.className = "status failed";
    taskStatus.textContent = e.message;
    setResultState("failed", "生成失败");
    resultEl.innerHTML = errorPanel("这份周报暂时未能生成", e.message, null, state.file);
    bindResultActions();
  } finally {
    state.submitting = false;
    document.querySelectorAll("[data-action]").forEach((button) => (button.disabled = false));
    btnGenerate.disabled = false;
    if (state.inspect) refreshBlockers();
  }
}

function pollTask(taskId) {
  clearTimeout(state.pollTimer);
  const version = state.requestVersion;
  const poll = async () => {
    if (version !== state.requestVersion || taskId !== state.currentTaskId) return;
    try {
      const t = await apiGet(`/api/v1/tasks/${taskId}`);
      if (version !== state.requestVersion || taskId !== state.currentTaskId) return;
      if (t.status === "done" || t.status === "failed") {
        await renderResult(t, version);
        loadHistory();
      } else {
        taskStatus.textContent = taskProgress(t);
        const label = resultEl.querySelector(".result-pending strong");
        if (label) label.textContent = taskProgress(t);
        state.pollTimer = setTimeout(poll, document.hidden ? 4000 : 1000);
      }
    } catch (e) {
      if (version !== state.requestVersion) return;
      taskStatus.className = "status failed";
      taskStatus.textContent = "连接暂时中断，可重新查询任务";
      setResultState("failed", "连接中断");
      resultEl.innerHTML = errorPanel("连接暂时中断", "任务可能仍在处理，重新连接会查询原任务，不会重复生成。", taskId);
      bindResultActions();
    }
  };
  poll();
}

async function renderResult(t, version = state.requestVersion, initialTab = "overview") {
  if (version !== state.requestVersion || t.task_id !== state.currentTaskId) return;
  if (t.status === "failed") {
    taskStatus.className = "status failed";
    taskStatus.textContent = "任务失败：" + (t.error?.message || "请重试");
    resultEl.innerHTML = errorPanel("这份周报暂时未能生成", t.error?.message || "请检查数据后重试。", t.task_id, fileName(t.input_file));
    bindResultActions();
    setResultState("failed", "未成功");
    return;
  }
  if (t.status !== "done") {
    resultEl.innerHTML = errorPanel("任务状态待确认", "当前任务状态无法识别，请重新查询。", t.task_id);
    bindResultActions(); setResultState("failed", "状态待确认"); return;
  }
  setResultState("running", "正在读取成果");
  const [basisResponse, factsResponse, reportResponse] = await Promise.allSettled([
    apiGet(`/api/v1/tasks/${t.task_id}/basis`),
    apiGet(`/api/v1/tasks/${t.task_id}/facts`),
    apiGet(`/api/v1/tasks/${t.task_id}/report`),
  ]);
  if (version !== state.requestVersion || t.task_id !== state.currentTaskId) return;
  const basis = basisResponse.status === "fulfilled" ? basisResponse.value : null;
  const facts = factsResponse.status === "fulfilled" ? factsResponse.value.facts : [];
  const changes = factsResponse.status === "fulfilled" ? factsResponse.value.change_facts || [] : [];
  const report = reportResponse.status === "fulfilled" ? reportResponse.value.report : null;
  const deliverables = t.result?.deliverables || [];
  const taskId = encodeURIComponent(t.task_id);
  const fileUrl = (name) => `/api/v1/tasks/${taskId}/files/${encodeURIComponent(name)}`;
  const hasXlsx = deliverables.includes("data_summary.xlsx");
  const hasReport = deliverables.includes("report.md");
  const identity = basis ? summaryIdentity(basis.summary_validation) : { kind: "pending", label: "摘要身份暂未加载" };
  const scope = basis ? (basis.scope || (basis.report_week ? `${basis.report_week} ~ ${weekEnd(basis.report_week)}` : "全表数据汇总")) : "统计范围暂未加载";
  const title = basis ? (basis.report_week ? "销售数据周报" : "销售数据汇总") : "销售数据报告";
  const alerts = [];
  if (basis?.unit_status === "pending") alerts.push("金额单位待确认。本页、报告和汇总表均保留待确认标识，请确认后再对外交付。");
  if (basis?.compare_unavailable_reason) alerts.push(basis.compare_unavailable_reason);
  if (basis?.warnings) alerts.push(...basis.warnings);
  if (identity.kind === "warning") alerts.push(identity.label + "。请核对摘要后使用；计算结果与摘要身份分别记录。");
  if (!basis) alerts.push("数据依据暂未加载，统计范围、金额单位与核对状态无法确认。请重新读取后使用。");
  const partial = [basisResponse, factsResponse, reportResponse].some((response) => response.status === "rejected");
  if (partial) alerts.push("部分成果暂未加载。任务已保存，可点击重新读取恢复，无需重新生成。");
  const tabs = [["overview", "chart", "数字概览"], ["document", "file", "报告正文"], ["charts", "chart", "销售图表"], ["basis", "shield", "数据依据"]];
  let html = `<div class="report-heading"><div><div class="eyebrow">WORKMATE / 销售分析</div><h1>${escapeHtml(title)}</h1><p>${escapeHtml(fileName(t.input_file))} · ${escapeHtml(taskDate(t.created_at))}</p></div><div class="report-actions">`;
  if (hasXlsx) html += `<a class="primary compact" href="${fileUrl("data_summary.xlsx")}" download>${icon("download")}下载汇总表</a>`;
  if (hasReport) html += `<a class="secondary compact" href="${fileUrl("report.md")}" download>${icon("file")}下载报告</a>`;
  html += `</div></div><div class="report-meta"><span class="meta-pill">${icon("clock")}${escapeHtml(scope)}</span><span class="meta-pill ${basis?.unit_status === "pending" ? "pending" : ""}">金额单位 · ${escapeHtml(basis?.unit || "单位待确认")}</span><span class="meta-pill ${identity.kind}">${icon("spark")}${escapeHtml(identity.label)}</span></div>`;
  if (alerts.length) html += `<div class="report-alerts">${[...new Set(alerts)].map((alert) => `<p class="warn">${escapeHtml(alert)}</p>`).join("")}${partial ? `<button class="secondary compact" data-reload="${escapeAttr(t.task_id)}">重新读取成果</button>` : ""}</div>`;
  html += `<div class="report-tabs" role="tablist" aria-label="成果内容">${tabs.map(([id, name, label]) => `<button id="tab-${id}" role="tab" aria-selected="false" aria-controls="panel-${id}" tabindex="-1" data-tab="${id}">${icon(name)}${label}</button>`).join("")}</div>`;
  const sectionError = (name) => `<p class="section-load-error">${name}暂未加载，请点击上方重新读取成果。</p>`;
  const coreIds = ["total_sales", "order_count", "avg_order_value", "line_count"];
  html += '<section id="panel-overview" role="tabpanel" aria-labelledby="tab-overview" tabindex="0">';
  if (factsResponse.status === "fulfilled") {
    html += `<div class="metric-grid">${coreIds.map((id) => {
      const fact = facts.find((item) => item.id === id);
      const value = fact?.value;
      const formatted = typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN", { maximumFractionDigits: 8 }) : "待确认";
      const growth = facts.find((item) => item.id === "mom_growth");
      const foot = id === "total_sales" ? (growth?.value != null ? `<span class="${growth.value < 0 ? "down" : "up"}">较上一自然周 ${growth.value > 0 ? "+" : ""}${escapeHtml(fmtFactValue(growth))}</span>` : "周环比 · 待确认 / 不适用") : id === "order_count" ? "按完整订单号去重" : id === "line_count" ? "统计范围内的明细记录" : "销售额 ÷ 订单量";
      return `<div class="metric-card"><span class="metric-label">${escapeHtml(fact?.label || ({ total_sales: "总销售额", order_count: "订单量", avg_order_value: "客单价", line_count: "明细行数" })[id])}</span><span class="metric-value">${escapeHtml(formatted)}${value != null && fact?.unit ? `<small>${escapeHtml(fact.unit)}</small>` : ""}</span><div class="metric-foot">${foot}</div></div>`;
    }).join("")}</div>`;
  } else html += sectionError("关键数字");
  const conclusion = reportSection(report, "核心结论");
  const shares = facts.find((fact) => fact.id === "channel_share");
  const top5 = facts.find((fact) => fact.id === "top5");
  const amountUnit = facts.find((fact) => fact.id === "total_sales")?.unit;
  html += `<div class="overview-grid"><section class="panel overview-card"><h2>${icon("spark")}核心结论</h2><div class="insight-content">${report ? (conclusion ? renderMarkdown(conclusion) : '<p class="muted">这份历史报告未包含独立核心结论，请查看报告正文。</p>') : sectionError("报告正文")}</div><div class="insight-note"><span>摘要保留原文引用 · 业务质量需人工核对</span><button class="text-button" data-open-tab="document">阅读完整报告${icon("arrow")}</button></div>`;
  if (changes.length) html += `<div class="change-list"><h3>销售额变化 · 已有数据依据</h3>${changes.map((change) => `<p>${escapeHtml(formatChangeFact(change, amountUnit))}</p>`).join("")}</div>`;
  html += '</section><section class="panel overview-card"><h2>' + icon("chart") + '渠道表现</h2>';
  if (shares?.value && typeof shares.value === "object" && !Array.isArray(shares.value)) {
    html += Object.entries(shares.value).map(([name, value]) => `<div class="share-row"><div><span>${escapeHtml(name)}</span><span>${escapeHtml(fmtValue(value))}%</span></div><div class="share-track" aria-hidden="true"><div class="share-fill" style="width:${shareWidth(value)}%"></div></div></div>`).join("");
    html += '<p class="hint">按渠道销售额占比展示；不推测变化原因。</p>';
  } else html += '<p class="hint">渠道占比待确认或不适用，请在数据依据中查看计算范围。</p>';
  html += '<h3 class="mini-section-title">Top5 商品 · 按销售额排序</h3>';
  html += Array.isArray(top5?.value) ? `<div class="rank-list">${top5.value.map((name, index) => `<span class="rank-item"><b>${String(index + 1).padStart(2, "0")}</b>${escapeHtml(name)}</span>`).join("")}</div>` : '<p class="hint">商品排名待确认或不适用。</p>';
  html += '</section></div></section>';
  html += `<section id="panel-document" role="tabpanel" aria-labelledby="tab-document" tabindex="0" hidden><div class="panel report-document"><div class="document-label">WORKMATE · SALES REPORT</div><article class="report">${report ? renderMarkdown(report) : sectionError("报告正文")}</article></div></section>`;
  const charts = deliverables.filter((name) => name.startsWith("charts/"));
  const chartLabels = { "charts/trend.png": "每日销售趋势", "charts/top5.png": "Top5 商品销售额", "charts/channel.png": "渠道销售占比" };
  html += `<section id="panel-charts" role="tabpanel" aria-labelledby="tab-charts" tabindex="0" hidden><div class="chart-grid">${charts.length ? charts.map((name) => `<div class="chart-item"><div class="chart-header"><h2>${escapeHtml(chartLabels[name] || "销售数据图表")}</h2><a href="${fileUrl(name)}" download>下载图片</a></div><img src="${fileUrl(name)}" alt="${escapeAttr(chartLabels[name] || name)}" data-name="${escapeAttr(name)}" loading="lazy" /></div>`).join("") : '<div class="list-empty">本次任务没有可展示的图表<p>请查看报告正文及数据依据中的限制说明。</p></div>'}</div></section>`;
  html += `<section id="panel-basis" role="tabpanel" aria-labelledby="tab-basis" tabindex="0" hidden><div class="basis-heading"><h2>本次报告的计算口径</h2><span class="meta-pill ${basis?.verify?.passed ? "verified" : "pending"}">${basis?.verify?.passed ? "数字核对通过" : "核对状态待确认"}</span></div>${basis ? renderSummary(basis) : sectionError("计算口径")}<div class="basis-heading"><h2>事实与计算依据</h2><span class="hint">来源、公式与核对状态</span></div>${factsResponse.status === "fulfilled" ? `<div class="facts">${facts.map((fact) => `<div class="fact"><b>${escapeHtml(fact.label)}</b><span class="fact-val">${escapeHtml(fmtFactValue(fact))}</span><span class="fact-src">来源 ${escapeHtml(fact.source_col || "—")} · ${escapeHtml(fact.formula || "")}${fact.verified ? " · 已核对" : " · 待核对"}</span></div>`).join("")}</div>` : sectionError("事实依据")}<div class="basis-downloads">${deliverables.includes("analysis_basis.json") ? `<a class="download" href="${fileUrl("analysis_basis.json")}" download>下载完整依据文件</a>` : ""}${hasXlsx ? `<a class="download" href="${fileUrl("data_summary.xlsx")}" download>下载汇总表</a>` : ""}</div></section>`;
  resultEl.innerHTML = html;
  if (state.view === "report") {
    const heading = resultEl.querySelector("h1");
    if (heading) { heading.tabIndex = -1; heading.focus({ preventScroll: true }); }
  }
  taskStatus.className = "status success";
  taskStatus.textContent = partial ? "部分成果待读取" : "已完成";
  setResultState(partial ? "failed" : "success", partial ? "部分待读取" : "已完成");
  bindResultActions();
  selectTab(tabs.some(([id]) => id === initialTab) ? initialTab : "overview", false);
  resultEl.querySelectorAll("[role=tab]").forEach((button) => {
    button.addEventListener("click", () => selectTab(button.dataset.tab));
    button.addEventListener("keydown", (event) => {
      const names = tabs.map(([id]) => id);
      const index = names.indexOf(button.dataset.tab);
      const next = event.key === "ArrowRight" ? names[(index + 1) % names.length] : event.key === "ArrowLeft" ? names[(index + names.length - 1) % names.length] : event.key === "Home" ? names[0] : event.key === "End" ? names.at(-1) : null;
      if (next) { event.preventDefault(); selectTab(next); $(`#tab-${next}`).focus(); }
    });
  });
  resultEl.querySelectorAll("[data-open-tab]").forEach((button) => button.addEventListener("click", () => {
    selectTab(button.dataset.openTab);
    $(".report-tabs").scrollIntoView({ block: "start" });
    $(`#panel-${button.dataset.openTab}`).focus({ preventScroll: true });
  }));
  resultEl.querySelectorAll("img").forEach((img) => {
    img.addEventListener("error", () => {
      const holder = img.parentElement;
      img.replaceWith(Object.assign(document.createElement("p"), { className: "chart-error", textContent: "图表暂时无法加载。请点击重新加载，或使用上方下载图片。" }));
      const retry = document.createElement("button");
      retry.className = "secondary compact"; retry.textContent = "重新加载图表";
      retry.addEventListener("click", () => viewTask(t.task_id)); holder.appendChild(retry);
    });
  });
}

function selectTab(tab, writeUrl = true) {
  if (!$(`#tab-${tab}`)) return;
  resultEl.querySelectorAll("[role=tab]").forEach((button) => {
    const selected = button.dataset.tab === tab;
    button.setAttribute("aria-selected", String(selected)); button.tabIndex = selected ? 0 : -1;
  });
  resultEl.querySelectorAll("[role=tabpanel]").forEach((panel) => (panel.hidden = panel.id !== `panel-${tab}`));
  if (writeUrl && state.view === "report") updateUrl(tab);
}
function errorPanel(title, message, taskId, sourceFile = "") {
  return `<div class="result-error">${icon("file")}<h2>${escapeHtml(title)}</h2>${sourceFile ? `<p class="hint">${escapeHtml(sourceFile)}</p>` : ""}<p>${escapeHtml(message)}</p><div class="error-actions">${taskId ? `<button class="secondary" data-reload="${escapeAttr(taskId)}">重新查询任务</button>` : ""}<button class="primary" data-return-check data-return-file="${escapeAttr(sourceFile || "")}">返回重新检查${icon("arrow")}</button></div></div>`;
}
function bindResultActions() {
  resultEl.querySelectorAll("[data-reload]").forEach((button) => button.addEventListener("click", () => viewTask(button.dataset.reload)));
  resultEl.querySelectorAll("[data-return-check]").forEach((button) => button.addEventListener("click", () => {
    clearTimeout(state.pollTimer); state.requestVersion++;
    const sourceFile = button.dataset.returnFile;
    navigate("home");
    if (sourceFile && state.inspect && state.file === sourceFile) { renderInspect(); showStep(2); reInspect(); }
    else {
      newReport();
      if (sourceFile && [...fileSelect.options].some((option) => option.value === sourceFile)) {
        fileSelect.value = sourceFile; refreshStep1(); btnInspect.click();
      }
    }
  }));
}

btnRestart.addEventListener("click", newReport);
function newReport() {
  if (state.submitting || state.uploadPending) return;
  clearTimeout(state.pollTimer);
  state.requestVersion++;
  state.currentTaskId = null;
  state.file = null;
  state.mapping = {};
  state.inspect = null;
  state.inspectVersion++;
  state.inspectPending = false;
  fileSelect.disabled = false;
  fileUpload.disabled = false;
  state.inspectError = null;
  state.amountMode = null;
  state.unit = null;
  state.reportWeek = null;
  state.compareWeek = null;
  state.complete = { report: false, compare: false };
  resultEl.innerHTML = emptyResult;
  uploadMsg.textContent = "";
  btnInspect.innerHTML = `检查数据并继续${icon("arrow")}`;
  refreshStep1();
  setResultState("", "等待生成");
  navigate("home");
  showStep(1);
  window.scrollTo(0, 0);
  document.querySelectorAll("#history button").forEach((button) => button.classList.remove("active"));
}

function showStep(n) {
  state.step = n;
  const titles = ["开始制作周报", "确认字段与口径", "选择报告周次", "查看生成成果"];
  $("#flow-title").textContent = titles[n - 1];
  $("#flow-count").textContent = `${String(n).padStart(2, "0")} / 04`;
  $("#recent-section").hidden = n !== 1;
  $(".home-heading").hidden = n !== 1;
  $(".delivery-guide").hidden = n === 4;
  $("#compose-area").classList.toggle("focused", n !== 1);
  for (let i = 1; i <= 4; i++) {
    document.getElementById(`step-${i}`).hidden = i !== n;
    const step = document.querySelector(`.step[data-step="${i}"]`);
    step.classList.toggle("active", i === n);
    step.classList.toggle("completed", i < n);
    if (i === n) step.setAttribute("aria-current", "step");
    else step.removeAttribute("aria-current");
  }
  if (state.view === "home") window.scrollTo(0, 0);
  if (state.view === "home" && n > 1) $("#flow-title").focus({ preventScroll: true });
}

function setResultState(kind, label) {
  const badge = $("#result-state");
  badge.className = `result-state ${kind}`.trim(); badge.textContent = label;
  btnRestart.textContent = kind === "failed" ? "返回重新检查" : "开始制作新周报";
  $("#task-hint").textContent = kind === "failed" ? "请按提示修正数据，或返回重新检查字段和统计口径。" : "生成结束后，成果会自动打开，也可从历史任务找回。";
}
function fmtValue(v) {
  if (v == null) return "待确认";
  return String(v);
}
function fmtFactValue(f) {
  if (Array.isArray(f.value)) return f.value.map(fmtValue).join("、");
  if (f.value && typeof f.value === "object") {
    return Object.entries(f.value).map(([name, value]) => `${name} ${fmtValue(value)}${f.unit || ""}`).join(" · ");
  }
  return `${fmtValue(f.value)}${f.value == null || !f.unit ? "" : " " + f.unit}`;
}
function fmtSize(n) {
  return n > 1024 * 1024 ? (n / 1024 / 1024).toFixed(1) + "MB" : n > 1024 ? (n / 1024).toFixed(1) + "KB" : n + "B";
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function escapeAttr(s) {
  return escapeHtml(s);
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

init();
