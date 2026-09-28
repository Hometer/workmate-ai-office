"""周报范式（PRD §3.6）：report.md 固定结构渲染。"""
from __future__ import annotations

from typing import Any


def _fmt(v: Any) -> str:
    if v is None:
        return "本表无此数据"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return f"{v:,}"


def render_report(metrics: dict, summary: str) -> str:
    lines = ["# 销售数据周报", "", "## 本周核心结论", "", summary, "", "## 关键数字", ""]
    lines.append(f"- 总销售额：{_fmt(metrics.get('total_sales'))}")
    lines.append(f"- 订单量：{_fmt(metrics.get('order_count'))}")
    lines.append(f"- 客单价：{_fmt(metrics.get('avg_order_value'))}")
    mom = metrics.get("mom_growth")
    if mom is None:
        lines.append("- 环比增长率：本表无此数据")
    else:
        lines.append(f"- 环比增长率：{mom * 100:.2f}%")

    lines += ["", "## Top5 商品", ""]
    top5 = metrics.get("top5") or []
    if top5:
        for i, item in enumerate(top5, 1):
            lines.append(f"{i}. {item['name']} — {item['sales']:,.2f}")
    else:
        lines.append("本表无此数据")

    lines += ["", "## 渠道表现", ""]
    channel = metrics.get("channel_share") or []
    if channel:
        for item in channel:
            lines.append(f"- {item['name']}：{item['share'] * 100:.2f}%")
    else:
        lines.append("本表无此数据")

    lines.append("")
    return "\n".join(lines)


def conservative_summary(metrics: dict) -> str:
    """保守模板：审核/模型失败时的确定性降级总结（不编造，只复述数字）。"""
    parts = [f"本周总销售额 {_fmt(metrics.get('total_sales'))}", f"订单量 {_fmt(metrics.get('order_count'))}"]
    avg = metrics.get("avg_order_value")
    parts.append(f"客单价 {_fmt(avg)}" if avg is not None else "客单价 本表无此数据")
    mom = metrics.get("mom_growth")
    parts.append(f"环比增长率 {mom * 100:.2f}%" if mom is not None else "环比增长率 本表无此数据")
    top5 = metrics.get("top5") or []
    if top5:
        parts.append("Top5 商品：" + "、".join(i["name"] for i in top5))
    return "；".join(parts) + "。"
