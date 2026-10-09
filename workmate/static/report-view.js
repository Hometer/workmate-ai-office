// Safe reading projection. Saved Markdown and server facts remain unchanged.
/** @param {unknown} value */
export function escapeText(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] || char);
}

/** Unique, safe IDs only: duplicate facts cannot support an unambiguous link.
 * @param {unknown} facts */
export function citationFacts(facts) {
  /** @type {Map<string, string>} */
  const labels = new Map();
  const duplicates = new Set();
  if (!Array.isArray(facts)) return labels;
  for (const fact of facts) {
    if (!fact || typeof fact.id !== "string" || !/^[a-zA-Z][\w-]{0,63}$/.test(fact.id)) continue;
    if (labels.has(fact.id)) duplicates.add(fact.id);
    else labels.set(fact.id, typeof fact.label === "string" ? fact.label : fact.id);
  }
  for (const id of duplicates) labels.delete(id);
  return labels;
}

/** Readable chart context from saved facts only; never infer points from a PNG.
 * @param {string} name @param {unknown} facts @param {string} [scope] */
export function renderChartSummary(name, facts, scope = "") {
  /** @type {Record<string, string>} */
  const factIds = { "charts/trend.png": "total_sales", "charts/top5.png": "top5", "charts/channel.png": "channel_share" };
  const id = factIds[name];
  if (!id) return '<p>此图表的摘要待确认，请放大查看原图并核对数据依据。</p>';
  const labels = citationFacts(facts);
  const fact = labels.has(id) && Array.isArray(facts) ? facts.find((item) => item?.id === id) : null;
  const value = fact?.value;
  const source = fact ? `<button type="button" class="citation-link" data-citation="${id}" aria-label="查看依据：${escapeText(labels.get(id))}">查看依据</button>` : "";
  const range = scope.trim() ? scope : typeof fact?.range === "string" && fact.range.trim() ? fact.range : "范围待确认";
  /** @param {number} number @param {boolean} [money] */
  const numberText = (number, money = false) => number.toLocaleString("zh-CN", { minimumFractionDigits: money ? 2 : 0, maximumFractionDigits: 8 });
  let body;
  if (id === "total_sales") {
    const unit = typeof fact?.unit === "string" && fact.unit.trim() ? fact.unit : "单位待确认";
    body = typeof value === "number" && Number.isFinite(value)
      ? `<p>总销售额 <strong>${escapeText(numberText(value, true))} ${escapeText(unit)}</strong></p>`
      : '<p>总销售额待确认。</p>';
    body += '<p>逐日数值可放大查看原图。</p>';
  } else if (id === "top5") {
    body = Array.isArray(value) && value.length && value.every((item) => typeof item === "string" && item.trim())
      ? `<p>按销售额排名</p><ol>${value.map((item) => `<li>${escapeText(item)}</li>`).join("")}</ol><p>各商品的销售金额可放大查看原图。</p>`
      : '<p>商品排名待确认或不适用，请查看数据依据。</p>';
  } else {
    const entries = value && typeof value === "object" && !Array.isArray(value) ? Object.entries(value) : [];
    body = entries.length
      ? `<ul>${entries.map(([channel, share]) => `<li>${escapeText(channel)} · <strong>${typeof share === "number" && Number.isFinite(share) ? `${escapeText(numberText(share))}%` : "占比待确认"}</strong></li>`).join("")}</ul>`
      : '<p>渠道占比待确认或不适用，请查看数据依据。</p>';
    if (entries.some(([, share]) => typeof share === "number" && Number.isFinite(share) && (share < 0 || share > 100))) {
      body += '<p>占比含负值或超过 100%，请结合原始数据与计算口径核对。</p>';
    }
  }
  return `${body}<p>统计范围：${escapeText(range)}</p><p>来源：本次任务事实。${source}</p>`;
}

/** @param {string} text @param {Map<string,string>} labels */
function inline(text, labels) {
  let result = "", cursor = 0;
  for (const match of text.matchAll(/\[([^\]\n]{1,80})\]/g)) {
    const index = match.index;
    result += escapeText(text.slice(cursor, index));
    const id = match[1];
    result += labels.has(id)
      ? `<button type="button" class="citation-link" data-citation="${escapeText(id)}" aria-label="查看依据：${escapeText(labels.get(id))}">查看依据</button>`
      : `<span class="citation-unavailable">${escapeText(match[0])} · 依据不可用</span>`;
    cursor = index + match[0].length;
  }
  return result + escapeText(text.slice(cursor));
}

/** Minimal Markdown: text is escaped before any trusted markup is generated.
 * @param {string|null|undefined} markdown @param {unknown} [facts] */
export function renderMarkdown(markdown, facts) {
  const labels = citationFacts(facts);
  let html = "";
  /** @type {string|null} */
  let list = null;
  const closeList = () => { if (list) { html += `</${list}>`; list = null; } };
  for (const line of String(markdown || "").split("\n")) {
    const heading = line.match(/^(#{1,3}) (.*)$/);
    if (heading) { closeList(); const n = heading[1].length; html += `<h${n}>${inline(heading[2], labels)}</h${n}>`; }
    else if (/^- /.test(line)) { if (list !== "ul") { closeList(); html += "<ul>"; list = "ul"; } html += `<li>${inline(line.slice(2), labels)}</li>`; }
    else if (/^\d+\. /.test(line)) { if (list !== "ol") { closeList(); html += "<ol>"; list = "ol"; } html += `<li>${inline(line.replace(/^\d+\. /, ""), labels)}</li>`; }
    else if (!line.trim()) closeList();
    else { closeList(); html += `<p>${inline(line, labels)}</p>`; }
  }
  closeList();
  return html;
}

/** Fold only the recognizable heading-and-metadata prefix; preserve all text.
 * Legacy prose is kept in its original order rather than guessed as metadata.
 * @param {string} markdown @param {unknown} [facts] */
export function renderReportDocument(markdown, facts) {
  const lines = markdown.split("\n");
  const firstSection = lines.findIndex((line) => /^## /.test(line));
  if (firstSection <= 0) return renderMarkdown(markdown, facts);
  const prefix = lines.slice(0, firstSection);
  if (!prefix.every((line) => !line.trim() || /^# /.test(line) || /^- /.test(line))) return renderMarkdown(markdown, facts);
  const title = prefix.filter((line) => /^# /.test(line)).join("\n");
  const metadata = prefix.filter((line) => !/^# /.test(line)).join("\n").trim();
  return renderMarkdown(title, facts) + renderMarkdown(lines.slice(firstSection).join("\n"), facts)
    + (metadata ? `<details class="report-details"><summary>统计口径与核对说明</summary>${renderMarkdown(metadata, facts)}</details>` : "");
}
