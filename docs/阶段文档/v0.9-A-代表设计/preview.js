/* 独立设计预览：只读已授权合成样例快照，不提交业务任务。 */
const main = document.querySelector("#main");
const params = new URLSearchParams(location.search);
const page = ["home", "fields", "report"].includes(params.get("page")) ? params.get("page") : "home";
let scenario = ["normal", "pending", "fallback"].includes(params.get("sample")) ? params.get("sample") : "normal";
const tabs = [["overview", "数字概览"], ["document", "报告正文"], ["charts", "销售图表"], ["basis", "数据依据"]];
let activeTab = tabs.some(([key]) => key === params.get("tab")) ? params.get("tab") : "overview";
let samples;
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="#${name}"/></svg>`;
const number = (value, digits = 2) => Number(value).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const fact = (sample, id) => sample.facts.find((item) => item.id === id);
const factValue = (item) => item?.value == null ? "待确认" : typeof item.value === "number" ? number(item.value, ["order_count", "line_count"].includes(item.id) ? 0 : 2) : Array.isArray(item.value) ? item.value.join("、") : Object.entries(item.value).map(([name, value]) => `${name} ${number(value)}%`).join(" · ");
const title = (sample) => sample.basis.report_week ? "销售数据周报" : "销售数据汇总";
const shortScope = (sample) => sample.basis.report_week ? "09.28 — 10.04" : "全表范围";
const ref = (id, label = "查看依据") => `<button class="reference" type="button" data-fact="${escape(id)}" aria-label="${escape(label)}：${escape(fact(samples[scenario], id)?.label || id)}">${escape(label)}</button>`;
const review = (text) => `<aside class="review-instruction"><strong>本页评审重点</strong> ${text}<br>设计预览不保存配置、不创建任务。正式界面将在方向确认后实现。</aside>`;
const taskUrl = (sample, name) => `http://127.0.0.1:8766/api/v1/tasks/${encodeURIComponent(sample.taskId)}/files/${encodeURIComponent(name)}`;

document.querySelectorAll(".review-bar [data-page]").forEach((link) => {
  link.classList.toggle("active", link.dataset.page === page);
  if (link.dataset.page === page) link.setAttribute("aria-current", "page");
});
document.querySelector("[data-nav=home]").classList.toggle("active", page === "home");
document.querySelector("#breadcrumb").textContent = { home: "工作台", fields: "制作周报", report: "报告阅读" }[page];

try {
  const response = await fetch("samples.json");
  if (!response.ok) throw new Error("未能读取设计样例");
  samples = (await response.json()).scenarios;
  if (page === "home") renderHome();
  else if (page === "fields") renderFields();
  else renderReport();
} catch {
  main.innerHTML = '<div class="card form-card"><h1>设计样例暂未加载</h1><p class="muted">请通过本地预览地址打开，或刷新后重试。</p><a class="button secondary" href="">刷新预览</a></div>';
}

function renderHome() {
  const isFirst = params.get("first") === "1";
  main.innerHTML = `<div class="page-heading"><div><div class="eyebrow">WORKSPACE</div><h1>${isFirst ? "从一张销售表开始" : "周报工作台"}</h1><p>${isFirst ? "确认数据，生成一份清楚、可核对的销售报告。" : "接着上次的工作，或开始新一周的分析。"}</p></div><div class="heading-tools"><label><span class="caption">预览场景 </span><select id="home-mode" class="small-select" aria-label="首页使用场景"><option value="repeat" ${!isFirst ? "selected" : ""}>已有成果</option><option value="first" ${isFirst ? "selected" : ""}>首次使用</option></select></label>${!isFirst ? `<a class="button primary" href="?page=fields">${icon("plus")}新建周报</a>` : ""}</div></div>
  ${isFirst ? `<section class="welcome"><h1>让你的周报，更快完成。</h1><p>上传销售表，确认口径，查看报告与图表。</p><div class="card welcome-card"><span class="large-icon">${icon("chart")}</span><h2>制作第一份销售报告</h2><p>支持 Excel 和 CSV，单文件不超过 20 MB。<br>原始销售表始终只读，报告与历史保存在本机。</p><a class="button primary" href="?page=fields">选择销售表 ${icon("arrow")}</a><a class="text-link" href="?page=report&sample=normal" style="margin-left:16px">看看样例报告</a></div><div class="guide-steps"><span><b>1</b>选择数据</span><span><b>2</b>确认口径</span><span><b>3</b>查看成果</span></div><p class="caption">样例为已授权合成数据，不代表你的业务。</p></section>` : `<section aria-labelledby="recent-title"><div class="section-header"><div><h2 id="recent-title">最近成果</h2><span class="badge">3 份设计样例</span></div><a class="text-link" href="http://127.0.0.1:8766/?view=library">查看实际历史 ${icon("arrow")}</a></div><div class="card recent-card">${Object.entries(samples).map(([key, sample]) => `<div class="task-row"><span class="file-tile">${icon("file")}</span><div class="task-name"><strong>${escape(title(sample))} · ${shortScope(sample)}</strong><span>${escape(sample.file)}</span><small class="task-inline-status ${key === "normal" ? "success" : "warning"}">${key === "normal" ? "已生成" : key === "pending" ? "单位待确认" : "降级摘要"}</small></div><span class="task-scope">${escape(sample.basis.unit)}<small>合成数据 · 原版成果</small></span><span class="badge ${key === "normal" ? "success" : "warning"}">${key === "normal" ? "已生成" : key === "pending" ? "单位待确认" : "降级摘要"}</span><a class="row-open" href="?page=report&sample=${key}">查看 ${icon("arrow")}</a></div>`).join("")}</div></section><div class="home-lower"><section class="card start-card"><span class="large-icon">${icon("chart")}</span><div><h2>开始一份新报告</h2><p>使用一张销售表，生成摘要、图表和汇总表。先检查字段，再确认统计范围。</p><a class="text-link" href="?page=fields">选择销售数据 ${icon("arrow")}</a></div></section><section class="card quiet-card">${icon("shield")}<div><h2>数据始终在本机</h2><p>原表只读，报告单独保存。每一个关键数字，都能回查对应的计算依据。</p><a class="text-link" href="?page=report&tab=basis">查看依据示例 ${icon("arrow")}</a></div></section></div><p class="sample-note">${icon("file")}以上是设计评审样例，正式首页将读取你的实际任务，不显示固定样例。</p>`}
  ${review("有成果时首屏直接看到最近工作；首次使用收起历史，突出开始入口。请看侧栏密度、信息顺序与留白。")}`;
  document.querySelector("#home-mode").addEventListener("change", (event) => { location.href = `?page=home${event.target.value === "first" ? "&first=1" : ""}`; });
}

function renderFields() {
  const mappings = [["sales", "销售额", "必填"], ["date", "日期", ""], ["product", "商品", ""], ["channel", "渠道", ""], ["order", "订单号", ""]];
  const cols = ["销售额", "日期", "商品", "渠道", "订单号", "币种"];
  main.innerHTML = `<ol class="stepper" aria-label="制作步骤"><li class="completed"><b>✓</b>选择数据</li><li class="active" aria-current="step"><b>2</b>确认口径</li><li><b>3</b>选择周次</li><li><b>4</b>查看成果</li></ol><div class="page-heading"><div><h1>确认这张表的含义</h1><p>核对字段与金额口径，让报告按正确的方式计算。</p></div></div><div class="field-layout"><section class="card form-card"><div class="source-strip"><span class="file-tile">${icon("file")}</span><div><strong>M38-sales-acceptance.csv</strong><p>5 行 · 8 列 · 合成数据</p></div><span class="badge success">样例摘要</span></div><div class="form-section"><h2>字段对应</h2><p>请选择每个业务字段在表格中对应的列。</p><div class="mapping-grid">${mappings.map(([id, label, hint]) => `<div class="field"><label for="mapping-${id}">${label}${hint ? `<span>${hint}</span>` : ""}</label><select id="mapping-${id}" aria-describedby="mapping-demo">${id !== "sales" ? '<option value="">不指定</option>' : ""}${cols.map((col) => `<option ${samples.normal.basis.field_mapping[id] === col ? "selected" : ""}>${col}</option>`).join("")}</select></div>`).join("")}</div><p id="mapping-demo" class="caption" style="margin-top:12px">此处仅演示排布。正式页面修改字段后将重新检查数据。</p></div><fieldset class="form-section" style="border-left:0;border-right:0;border-bottom:0;padding-left:0;padding-right:0"><legend><h2>金额口径</h2></legend><p>金额在每一行代表什么？请按原表的实际含义选择。</p><div class="radio-options"><label class="radio-option"><input type="radio" name="amount" value="A" checked><span><strong>A · 每行金额相加</strong><small>每行是这条商品或明细的金额，报告将逐行相加。</small></span></label><label class="radio-option"><input type="radio" name="amount" value="B"><span><strong>B · 整单金额去重</strong><small>同一订单的每行重复记录整单金额，按完整订单号去重计算。</small></span></label></div></fieldset><div class="form-section"><h2>金额单位</h2><p>沿用原表单位。没有明确单位时，保留“待确认”，不自动换汇。</p><div class="field unit-field"><label for="unit">本次报告使用的单位</label><input id="unit" value="USD" placeholder="例如 元 / USD" aria-describedby="unit-hint"><span class="caption" id="unit-hint">样例原表币种为 USD；本预览修改不会保存。</span></div><p class="form-notice" id="unit-warning" hidden>金额单位待确认。报告将持续显示这一限制，不猜测币种。</p></div><div class="form-actions"><span class="caption">下一步选择周次，并确认数据覆盖情况。</span><div><a class="button secondary" href="?page=home">返回</a> <button class="button primary" id="next-step">继续选择周次 ${icon("arrow")}</button></div></div><p class="demo-message" role="status" id="fields-message" hidden></p></section><aside class="field-aside"><div><h3>这份数据的边界</h3><ul class="quality-list"><li>${icon("check")}<div><strong>原表只读</strong><small>报告单独保存</small></div></li><li>${icon("check")}<div><strong>个人信息不展示</strong><small>姓名、电话不进入设计快照</small></div></li><li>${icon("check")}<div><strong>统计结果可回查</strong><small>范围、字段和公式随报告保存</small></div></li></ul></div><div class="aside-note"><h3>还需要你确认什么？</h3><p>金额口径由你判断。数字核对只能检查计算，不能代替业务数据完整性确认。</p><p style="margin-top:12px">本页为布局设计。安全表格预览和可复用设置在 B 阶段开发。</p></div></aside></div>${review("主表单集中在左侧，说明缩到旁侧；确认来源、字段、口径和单位的阅读顺序是否清楚。")}`;
  document.querySelector("#unit").addEventListener("input", (event) => { document.querySelector("#unit-warning").hidden = Boolean(event.target.value.trim()); });
  document.querySelector("#next-step").addEventListener("click", () => {
    const message = document.querySelector("#fields-message");
    message.hidden = false;
    message.textContent = "这是字段确认页的设计预览，没有提交或保存。周次与完整性确认将继续沿用正式产品的现有步骤。可点上方“报告”查看阅读设计。";
    message.scrollIntoView({ block: "nearest" });
  });
}

function renderReport() {
  const sample = samples[scenario];
  const identity = scenario === "fallback" ? "确定性降级摘要" : "真实本地模型摘要";
  main.innerHTML = `<div class="report-back"><a href="?page=home">${icon("arrow")}返回工作台</a><label><span class="caption">报告样例 </span><select id="scenario" class="small-select" aria-label="选择报告样例"><option value="normal" ${scenario === "normal" ? "selected" : ""}>正常 · USD</option><option value="pending" ${scenario === "pending" ? "selected" : ""}>金额单位待确认</option><option value="fallback" ${scenario === "fallback" ? "selected" : ""}>全表 · 模型降级</option></select></label></div><div class="report-heading"><div><div class="eyebrow">SALES REPORT · 原版成果</div><h1>${title(sample)}${sample.basis.report_week ? " · 09.28 — 10.04" : " · 全表"}</h1><p class="scope-line">统计范围 ${escape(sample.basis.scope.replace(/^报告周 /, ""))}</p><p class="report-source">来源 ${escape(sample.file)} · 合成数据</p></div><div class="download-group"><a class="button secondary" href="${taskUrl(sample, "data_summary.xlsx")}">${icon("download")}下载原汇总表</a><a class="button primary" href="${taskUrl(sample, "report.md")}">${icon("download")}下载原报告</a></div></div><div class="report-meta"><span class="badge success">${icon("check")}数字核对通过</span><span class="badge ${scenario === "fallback" ? "warning" : ""}">${escape(identity)}</span><span class="plain-meta">单位 ${escape(sample.basis.unit)}</span><span class="plain-meta">口径 ${escape(sample.basis.amount_mode)}</span></div>
    ${scenario === "pending" ? '<div class="alert" role="status"><span>!</span><div><strong>金额单位待确认</strong><p>本报告不推测币种。请先确认单位，再对外交付。</p></div></div>' : scenario === "fallback" ? '<div class="alert" role="status"><span>!</span><div><strong>摘要已降级，请人工复核</strong><p>本次模型不可用，使用确定性摘要；计算事实仍可回查。口径 B 无法可靠分摊到商品，不展示商品排名。</p></div></div>' : ""}
    <div class="report-tabs" role="tablist" aria-label="报告内容">${tabs.map(([id, label]) => `<button role="tab" id="tab-${id}" aria-controls="panel-${id}" aria-selected="false" tabindex="-1" data-tab="${id}">${label}</button>`).join("")}</div>
    <section role="tabpanel" id="panel-overview" aria-labelledby="tab-overview" tabindex="0" hidden>${overview(sample)}</section>
    <section role="tabpanel" id="panel-document" aria-labelledby="tab-document" tabindex="0" hidden>${documentView(sample)}</section>
    <section role="tabpanel" id="panel-charts" aria-labelledby="tab-charts" tabindex="0" hidden>${chartsView(sample)}</section>
    <section role="tabpanel" id="panel-basis" aria-labelledby="tab-basis" tabindex="0" hidden>${basisView(sample)}</section>
    ${review("范围、单位与摘要身份常显；结论提前，详细口径折叠。点“查看依据”可跳到同一任务的对应事实。下载链接指向当前产品的既有原版成果，不是新导出。")}`;
  document.querySelector("#scenario").addEventListener("change", (event) => { scenario = event.target.value; updateUrl(); renderReport(); });
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => selectTab(button.dataset.tab));
    button.addEventListener("keydown", (event) => {
      const ids = tabs.map(([id]) => id); const index = ids.indexOf(button.dataset.tab);
      const next = event.key === "ArrowRight" ? ids[(index + 1) % ids.length] : event.key === "ArrowLeft" ? ids[(index + ids.length - 1) % ids.length] : event.key === "Home" ? ids[0] : event.key === "End" ? ids.at(-1) : null;
      if (next) { event.preventDefault(); selectTab(next); document.querySelector(`#tab-${next}`).focus(); }
    });
  });
  document.querySelectorAll("[data-fact]").forEach((button) => button.addEventListener("click", () => {
    const id = button.dataset.fact;
    selectTab("basis");
    document.querySelectorAll(".fact.focused").forEach((item) => item.classList.remove("focused"));
    const target = document.getElementById(`fact-${id}`);
    if (target) { target.classList.add("focused"); target.scrollIntoView({ block: "center" }); target.focus({ preventScroll: true }); }
  }));
  document.querySelectorAll("[data-zoom]").forEach((button) => button.addEventListener("click", () => {
    document.querySelector("#dialog-chart").innerHTML = chart(sample, button.dataset.zoom, false);
    document.querySelector("#chart-dialog-title").textContent = { products: "商品销售额图表设计", channels: "渠道占比图表设计", trend: "每日销售趋势图表设计" }[button.dataset.zoom];
    document.querySelector("#chart-dialog").showModal();
  }));
  selectTab(activeTab, false);
}

function core(sample) {
  return escape(sample.core).replace(/\[([a-z_0-9]+)\]/g, (_, id) => fact(sample, id) ? ref(id) : '[依据不可用]').replace(/\n/g, "<br>");
}

function overview(sample) {
  const growth = fact(sample, "mom_growth");
  return `<div class="card conclusion"><h2>核心结论</h2><p>${core(sample)}</p><p class="caption">${scenario === "fallback" ? "确定性摘要，真实模型摘要未通过。" : "摘要取自原版真实本地模型结果，结构与事实校验通过。"}数字核对不代表业务数据完整。</p></div><div class="card metrics">${["total_sales", "order_count", "avg_order_value", "line_count"].map((id) => {
    const item = fact(sample, id);
    const foot = id === "total_sales" ? growth ? `较上一自然周 ${growth.value > 0 ? "+" : ""}${factValue(growth)}%` : "全表汇总 · 环比不适用" : id === "order_count" ? "按完整订单号去重" : id === "avg_order_value" ? "总销售额 ÷ 订单量" : "统计范围内的明细记录";
    return `<div class="metric"><span class="metric-label">${escape(item.label)}<button data-fact="${id}" aria-label="查看${escape(item.label)}的依据">↗</button></span><div class="metric-value">${escape(factValue(item))}<small>${escape(item.unit)}</small></div><p class="metric-foot ${id === "total_sales" && growth ? "growth" : ""}">${escape(foot)}</p></div>`;
  }).join("")}</div><div class="overview-grid">${chart(sample, "products")}${chart(sample, "channels")}</div>`;
}

function documentView(sample) {
  return `<article class="report-paper"><div class="document-eyebrow">WORKMATE / SALES REPORT</div><h2>${title(sample)}</h2><p class="document-subtitle">${escape(sample.basis.scope)} · ${escape(sample.basis.unit)} · 合成数据</p><div class="document-body"><h3 style="margin-top:0">核心结论</h3><p class="lead">${core(sample)}</p><h3>关键数字</h3><table class="document-table"><thead><tr><th scope="col">指标</th><th scope="col">本次结果</th><th scope="col">依据</th></tr></thead><tbody>${["total_sales", "order_count", "avg_order_value", "line_count", "mom_growth"].filter((id) => fact(sample, id)).map((id) => `<tr><td>${escape(fact(sample, id).label)}</td><td>${escape(factValue(fact(sample, id)))} ${escape(fact(sample, id).unit)}</td><td>${ref(id, "回查")}</td></tr>`).join("")}</tbody></table><h3>商品表现</h3>${sample.products.length ? `<p>${sample.products.map(({ name, value }) => `${escape(name)} ${number(value)} ${escape(sample.basis.unit)}`).join("；")}。</p><p class="caption">按商品销售额排序，不据此推测销量或增长原因。</p>${ref("top5")}` : '<p>本表无此数据。口径 B 无法可靠分摊到商品，不展示商品销售额排名。</p>'}<h3>渠道表现</h3><p>${Object.entries(fact(sample, "channel_share").value).map(([name, value]) => `${escape(name)} ${number(value)}%`).join("；")}。${ref("channel_share")}</p></div><details class="document-details"><summary>统计口径与核对说明</summary><dl><dt>统计范围</dt><dd>${escape(sample.basis.scope)}</dd><dt>金额口径</dt><dd>${sample.basis.amount_mode === "A" ? "A · 每行金额相加" : "B · 整单金额去重"}</dd><dt>金额单位</dt><dd>${escape(sample.basis.unit)}</dd><dt>摘要身份</dt><dd>${scenario === "fallback" ? "确定性降级摘要，模型不可用，请人工复核" : "真实本地模型选择事实，摘要结构与事实校验通过"}</dd><dt>核对边界</dt><dd>本次统计范围的数字已核对，不代表业务数据完整。</dd></dl></details></article>`;
}

function chart(sample, kind, zoom = true) {
  const shares = fact(sample, "channel_share");
  const names = { products: "商品销售额", channels: "渠道销售占比", trend: "每日销售趋势" };
  const rows = kind === "products" ? sample.products : kind === "channels" ? Object.entries(shares.value).map(([name, value]) => ({ name, value })) : [];
  const max = kind === "products" ? Math.max(...rows.map((item) => item.value), 0) : 100;
  const trend = scenario === "normal" ? `<svg class="trend-svg" viewBox="0 0 720 210" role="img" aria-label="报告周已记录日期销售额：9月28日125.50 USD，9月29日74.50 USD，9月30日400.00 USD。图表仅绘制已记录日期，不补造零值。"><g>${[35, 105, 175].map((y, index) => `<path class="gridline" d="M56 ${y}H684"/><text x="40" y="${y + 4}" text-anchor="end">${[400, 200, 0][index]}</text>`).join("")}</g><path class="trend-area" d="M88 131.075 364 148.925 640 35V175H88Z"/><path class="trend-line" d="M88 131.075 364 148.925 640 35"/><circle cx="88" cy="131.075" r="4"/><circle cx="364" cy="148.925" r="4"/><circle cx="640" cy="35" r="4"/><text x="88" y="119" text-anchor="middle">125.50</text><text x="364" y="137" text-anchor="middle">74.50</text><text x="640" y="23" text-anchor="middle">400.00</text><text x="88" y="199" text-anchor="middle">09/28</text><text x="364" y="199" text-anchor="middle">09/29</text><text x="640" y="199" text-anchor="middle">09/30</text></svg>` : `<p class="chart-unavailable">此代表设计只抽取该样例的聚合事实，未包含逐日数据。这里不绘制虚构趋势，可打开当前产品查看原图。</p>`;
  const body = kind === "trend" ? trend : rows.length ? `<div class="bar-list">${rows.map(({ name, value }) => `<div class="bar-row"><div><span>${escape(name)}</span><strong>${number(value)}${kind === "channels" ? "%" : ""}</strong></div><div class="bar-track" aria-hidden="true"><div class="bar-fill" style="width:${Math.max(0, Math.min(100, value / max * 100))}%"></div></div></div>`).join("")}</div>` : '<p class="chart-unavailable">口径 B 无法可靠分摊到商品，本次不展示商品排名。</p>';
  const change = kind === "channels" && sample.changes.length ? `<div class="change-note">${sample.changes.map((item) => `<p>${escape(item.name)}销售额${item.delta >= 0 ? "增加" : "减少"} ${number(Math.abs(item.delta))} ${escape(sample.basis.unit)}${item.contribution_pct != null ? `，占净增额 ${number(item.contribution_pct, 1)}%` : ""}。</p>`).join("")}<p class="caption">变化是数值差额，不代表已查明业务原因。</p></div>` : "";
  return `<section class="card chart-card"><div class="chart-title"><h2>${names[kind]}</h2><span>${kind === "channels" ? "单位 %" : `单位 ${escape(sample.basis.unit)}`}</span></div><p class="chart-subtitle">${kind === "products" ? "按销售额排序 · 最多 5 项" : kind === "channels" ? "按渠道销售额占比" : "仅展示原表已记录的日期，不补造零值"}</p>${body}${change}<div class="chart-footer"><span>${escape(sample.basis.scope)}<br>${scenario === "pending" ? "金额单位待确认 · 设计示意" : "已授权合成样例 · 设计示意"}</span>${zoom && (rows.length || kind === "trend" && scenario === "normal") ? `<button class="text-link" data-zoom="${kind}">放大查看</button>` : ""}</div></section>`;
}

function chartsView(sample) {
  return `<div class="chart-page">${chart(sample, "trend")}${chart(sample, "products")}${chart(sample, "channels")}</div><p class="basis-clarification">这些是图表视觉设计，使用既有合成结果；方向确认后才实现正式 PNG。历史下载图片不会因改版重绘。</p>`;
}

function basisView(sample) {
  return `<div class="basis-top"><div><h2>事实与计算依据</h2><p>点击结论引用后，定位到当前报告的对应事实。</p></div><span class="badge success">数字核对通过</span></div><div class="facts-grid">${sample.facts.map((item) => `<article class="card fact" id="fact-${escape(item.id)}" tabindex="-1"><div class="fact-heading"><h3>${escape(item.label)}</h3><span class="badge ${item.verified ? "success" : "warning"}">${item.verified ? "已核对" : "待核对"}</span></div><div class="fact-value">${escape(factValue(item))}<small>${item.unit && typeof item.value !== "object" ? escape(item.unit) : ""}</small></div><dl><dt>范围</dt><dd>${escape(item.range)}</dd><dt>字段</dt><dd>${escape(item.source_col || "由统计结果计算")}</dd><dt>公式</dt><dd>${escape(item.formula)}</dd><dt>排除</dt><dd>${escape(item.excluded)} 行</dd></dl></article>`).join("")}</div><p class="basis-clarification">依据来自同一任务 ${escape(sample.taskId)} 的保存事实。“已核对”只表示数字计算核对，不等于业务数据完整；本页不提供原表行级定位。</p><a class="text-link" href="${taskUrl(sample, "analysis_basis.json")}">${icon("download")}下载原始完整依据</a>`;
}

function selectTab(tab, write = true) {
  activeTab = tab;
  tabs.forEach(([id]) => {
    const button = document.getElementById(`tab-${id}`);
    button.setAttribute("aria-selected", String(id === tab)); button.tabIndex = id === tab ? 0 : -1;
    document.getElementById(`panel-${id}`).hidden = id !== tab;
  });
  if (write) updateUrl();
}

function updateUrl() {
  const url = new URL(location.href);
  url.searchParams.set("sample", scenario); url.searchParams.set("tab", activeTab);
  history.replaceState(null, "", url);
}

document.querySelector("#close-dialog").addEventListener("click", () => document.querySelector("#chart-dialog").close());
