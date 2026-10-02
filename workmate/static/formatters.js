// 返回纯文本；调用处必须转义后插入 HTML。
/** @param {{name: string, delta?: unknown, unit?: string|null, contribution_pct?: unknown}} change @param {string|null|undefined} [fallbackUnit] */
export function formatChangeFact(change, fallbackUnit) {
  const unit = change.unit || fallbackUnit || "单位待确认";
  const delta = change.delta;
  if (typeof delta !== "number" || !Number.isFinite(delta)) {
    return `${change.name}：变化金额待确认 ${unit}`;
  }
  const direction = delta > 0 ? "增加" : delta < 0 ? "减少" : "持平";
  const contribution = typeof change.contribution_pct === "number" && Number.isFinite(change.contribution_pct)
    ? `，占总变化 ${change.contribution_pct}%` : "";
  return `${change.name}：${direction} ${Math.abs(delta)} ${unit}${contribution}`;
}
