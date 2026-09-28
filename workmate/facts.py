"""事实卡与变化事实（PRD v0.5 F4）：每个结论可回查来源与计算式。"""
from __future__ import annotations


def _num(v):
    return round(float(v), 2) if isinstance(v, float) else v


def _card(fid, label, value, unit, source_col, formula, rng, excluded, verified) -> dict:
    return {
        "id": fid,
        "label": label,
        "value": value,
        "unit": unit,
        "source_col": source_col,
        "formula": formula,
        "range": rng,
        "excluded": excluded,
        "verified": verified,
    }


def build_facts(report_metrics: dict, mapping: dict, report_week: str | None, verify_ok: bool, excluded: int = 0) -> list[dict]:
    facts: list[dict] = []
    rng = report_week or "全表"
    facts.append(_card("total_sales", "报告周总销售额", _num(report_metrics["total_sales"]), "元", mapping.get("sales"), f"sum(销售额) · 口径{report_metrics.get('amount_mode')}", rng, excluded, verify_ok))
    facts.append(_card("line_count", "明细行数", report_metrics["line_count"], "行", None, "count(明细行)", rng, 0, verify_ok))
    if report_metrics["order_count"] is not None:
        facts.append(_card("order_count", "订单量", report_metrics["order_count"], "单", mapping.get("order"), "count(distinct 订单号)", rng, 0, verify_ok))
    if report_metrics["avg_order_value"] is not None:
        facts.append(_card("avg_order_value", "客单价", _num(report_metrics["avg_order_value"]), "元", None, "总销售额 ÷ 订单量", rng, 0, verify_ok))
    if report_metrics["mom_growth"] is not None:
        facts.append(_card("mom_growth", "环比增长率", round(report_metrics["mom_growth"] * 100, 2), "%", mapping.get("date"), "(报告周 − 对比周) ÷ 对比周", f"{report_week} vs 上一周", 0, verify_ok))
    if report_metrics.get("product_ranking_available") and report_metrics.get("top5"):
        facts.append(_card("top5", "Top5 商品", [i["name"] for i in report_metrics["top5"]], None, mapping.get("product"), "按商品销售额降序取前 5", rng, 0, verify_ok))
    if report_metrics.get("channel_share_available") and report_metrics.get("channel_share"):
        facts.append(_card("channel_share", "渠道占比", {i["name"]: round(i["share"] * 100, 2) for i in report_metrics["channel_share"]}, "%", mapping.get("channel"), "各渠道销售额 ÷ 总销售额", rng, 0, verify_ok))
    return facts


def build_change_facts(report_metrics: dict, compare_metrics: dict, mapping: dict) -> list[dict]:
    """最多 3 条确定性变化事实（仅当分类可完整覆盖、方向一致时给贡献占比）。"""
    changes: list[dict] = []
    total_r = report_metrics.get("total_sales")
    total_c = compare_metrics.get("total_sales")
    if not total_c or total_r == total_c:
        return changes
    delta = total_r - total_c
    ch_r = {i["name"]: i["share"] * total_r for i in (report_metrics.get("channel_share") or [])}
    ch_c = {i["name"]: i["share"] * total_c for i in (compare_metrics.get("channel_share") or [])}
    if ch_r and ch_c and set(ch_r) == set(ch_c):
        diffs = {k: ch_r[k] - ch_c.get(k, 0.0) for k in ch_r}
        for k, dv in sorted(diffs.items(), key=lambda kv: -abs(kv[1]))[:3]:
            if abs(dv) < 1e-9:
                continue
            share = None
            if delta != 0 and (dv > 0) == (delta > 0):
                share = round(abs(dv / delta) * 100, 1)
            changes.append({"dimension": "渠道", "name": k, "delta": round(dv, 2), "direction": "增加" if dv > 0 else "减少", "contribution_pct": share, "total_change": round(delta, 2)})
    return changes
