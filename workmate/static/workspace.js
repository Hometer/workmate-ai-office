// Pure presentation helpers. Server values remain the source of truth.
/** @typedef {{input_file?: string|null, status: string, steps?: {name: string, status: string}[]}} WorkspaceTask */
/** @typedef {{provider?: string, status?: string}} SummaryValidation */
/** @param {string|null|undefined} path */
export function fileName(path) {
  return String(path || "销售数据").split(/[\\/]/).pop() || "销售数据";
}

/** @param {WorkspaceTask[]} tasks */
export function filterTasks(tasks, query = "", status = "all") {
  const needle = query.trim().toLocaleLowerCase();
  return tasks.filter((task) => {
    const matches = status === "all" || (status === "running"
      ? ["running", "created"].includes(task.status) : task.status === status);
    return matches && fileName(task.input_file).toLocaleLowerCase().includes(needle);
  });
}

/** @param {SummaryValidation|null|undefined} validation */
export function summaryIdentity(validation) {
  if (!validation) return { kind: "pending", label: "历史摘要 · 身份未记录" };
  if (validation.provider === "mock") return { kind: "warning", label: "演示摘要 · 未调用真实模型" };
  if (validation.status === "fallback") return { kind: "warning", label: "降级摘要 · 模型摘要未通过" };
  if (validation.status !== "passed") return { kind: "pending", label: "摘要校验状态未确认" };
  return { kind: "verified", label: validation.provider === "ollama"
    ? "本地 AI 摘要 · 事实校验通过" : "AI 摘要 · 事实校验通过" };
}

/** @param {string|null|undefined} report @param {string} title */
export function reportSection(report, title) {
  const lines = String(report || "").split("\n");
  const start = lines.findIndex((line) => line.trim() === `## ${title}`);
  if (start < 0) return "";
  let end = lines.findIndex((line, index) => index > start && /^#{1,2} /.test(line));
  if (end < 0) end = lines.length;
  return lines.slice(start + 1, end).join("\n").trim();
}

/** @param {unknown} value */
export function shareWidth(value) {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
}

/** @param {WorkspaceTask} task */
export function taskProgress(task) {
  if (task.status === "created") return "任务已受理，等待开始";
  const step = task.steps?.find((item) => item.status === "running");
  /** @type {Record<string, string>} */
  const labels = { read_file: "正在读取销售数据", infer_columns: "正在识别数据字段", confirm_input: "正在保存统计口径",
    compute_metrics: "正在计算销售数字", verify_metrics: "正在核对计算结果", plot_chart: "正在生成销售图表",
    facts: "正在整理数据依据", write_summary: "正在生成销售摘要", safety_check: "正在核查报告内容",
    write_files: "正在保存报告与汇总表" };
  return labels[step?.name || ""] || "正在处理销售周报";
}
