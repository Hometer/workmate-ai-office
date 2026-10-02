"""周报范式（PRD v0.5 F4）：report.md 固定结构渲染。"""
from __future__ import annotations

from typing import Any


def _fmt(v: Any) -> str:
    if v is None:
        return "本表无此数据"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return f"{v:,}"


def render_report(
    metrics: dict,
    summary: str,
    *,
    title: str = "销售数据周报",
    amount_mode: str | None = None,
    report_week: str | None = None,
    warnings: list[str] | None = None,
    product_ranking_available: bool = True,
    channel_share_available: bool = True,
    unit: str = "元",
    summary_mode: bool = False,
    context: dict | None = None,
) -> str:
    lines = [f"# {title}", ""]

    meta = []
    if amount_mode:
        meta.append(f"- 金额口径：{'A（每行金额相加）' if amount_mode == 'A' else 'B（整单金额去重）'}")
    if report_week:
        meta.append(f"- 报告周：{report_week}（该周周一）")
    ctx = context or {}
    meta.append(f"- 统计范围：{ctx.get('scope') or ('全表' if summary_mode else report_week or '全表')}")
    meta.append(f"- 金额单位：{unit}；来源：{'字段识别' if ctx.get('unit_source') == 'field' else '人工声明' if ctx.get('unit_source') == 'user' else '待确认'}")
    if ctx.get("compare_week"):
        meta.append(f"- 对比周：{ctx['compare_week']}" + ("（无记录）" if ctx.get("compare_empty") else ""))
    meta.append("- 数字核对：本次统计范围已核对；不代表业务数据完整。")
    if not summary_mode:
        completeness = ctx.get("completeness") or {}
        meta.append(f"- 人工完整性确认：报告周{'已确认' if completeness.get('report') else '未确认'}，对比周{'已确认' if completeness.get('compare') else '未确认'}。")
    validation = ctx.get("summary_validation") or {}
    if validation.get("provider") == "mock":
        meta.append("- 总结身份：演示模式，未调用真实模型。")
    elif validation.get("status") == "fallback":
        meta.append("- 总结身份：确定性降级摘要，真实模型摘要未通过。")
    elif validation:
        meta.append("- 总结身份：真实本地模型选择事实，摘要结构与事实校验通过；业务质量仍须人工验收。")
    if meta:
        lines += meta + [""]

    lines += ["## 核心结论", "", summary, "", "## 关键数字", ""]
    lines.append(f"- 总销售额：{_fmt(metrics.get('total_sales'))} {unit}")
    lines.append(f"- 明细行数：{_fmt(metrics.get('line_count'))}")
    order_count = metrics.get("order_count")
    lines.append(f"- 订单量（订单号去重）：{_fmt(order_count) if order_count is not None else '待确认（无完整订单号）'}")
    avg_order_value = metrics.get("avg_order_value")
    lines.append(f"- 客单价：{_fmt(avg_order_value) if avg_order_value is not None else '待确认（订单量未知）'} {unit}")
    if not summary_mode:
        mom = metrics.get("mom_growth")
        if mom is None:
            lines.append("- 环比增长率：本表无此数据（需确认对比周数据完整）")
        else:
            lines.append(f"- 环比增长率：{mom * 100:.2f}%")

    lines += ["", "## Top5 商品", ""]
    if not product_ranking_available:
        lines.append("本表无此数据（口径 B 无法可靠分摊到商品）")
    else:
        top5 = metrics.get("top5") or []
        if top5:
            for i, item in enumerate(top5, 1):
                lines.append(f"{i}. {item['name']} — {item['sales']:,.2f} {unit}")
        else:
            lines.append("本表无此数据")

    lines += ["", "## 渠道表现", ""]
    if not channel_share_available:
        lines.append("本表无此数据（总额非正或存在负值/口径待确认）")
    else:
        channel = metrics.get("channel_share") or []
        if channel:
            for item in channel:
                lines.append(f"- {item['name']}：{item['share'] * 100:.2f}%")
        else:
            lines.append("本表无此数据")

    if warnings:
        lines += ["", "## 口径提示", ""]
        for w in warnings:
            lines.append(f"- {w}")

    lines.append("")
    return "\n".join(lines)


def conservative_summary(metrics: dict, summary_mode: bool = False, *, unit: str = "单位待确认") -> str:
    """保守模板：审核/模型失败时的确定性降级总结（不编造，只复述数字）。"""
    parts = [f"{'全表总销售额' if summary_mode else '报告周总销售额'} {_fmt(metrics.get('total_sales'))} {unit}", f"明细行数 {_fmt(metrics.get('line_count'))}"]
    order_count = metrics.get("order_count")
    parts.append(f"订单量 {order_count}" if order_count is not None else "订单量 待确认（无完整订单号）")
    avg = metrics.get("avg_order_value")
    parts.append(f"客单价 {_fmt(avg)} {unit}" if avg is not None else "客单价 待确认（订单量未知）")
    if not summary_mode:
        mom = metrics.get("mom_growth")
        parts.append(f"环比增长率 {mom * 100:.2f}%" if mom is not None else "环比增长率 本表无此数据")
    top5 = metrics.get("top5") or []
    if top5:
        parts.append("Top5 商品：" + "、".join(i["name"] for i in top5))
    return "；".join(parts) + "。"
