"""safety_check（s04 钩子）：内容审核，确定性规则，不调用模型。"""
from __future__ import annotations

import re

MAX_SUMMARY_LEN = 800
PLACEHOLDER_MARKERS = ["mock", "[todo]", "待生成", "编造", "占位", "lorem"]

# 金额型数字：绝对值 ≥100 或含小数
_NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _known_numbers(metrics: dict) -> list[float]:
    known: list[float] = []
    for key in ["total_sales", "order_count", "avg_order_value"]:
        v = metrics.get(key)
        if v is not None:
            known.append(float(v))
    mom = metrics.get("mom_growth")
    if mom is not None:
        known.extend([float(mom), float(mom) * 100])  # 环比可能写成比例或百分比
    for item in metrics.get("top5") or []:
        known.append(float(item["sales"]))
    for item in metrics.get("channel_share") or []:
        known.append(float(item["share"]) * 100)
    return known


def _matches_known(value: float, known: list[float]) -> bool:
    for k in known:
        if abs(value - k) <= max(0.01, abs(k) * 0.001):
            return True
    return False


def safety_check(summary: str, metrics: dict) -> dict:
    reasons: list[str] = []
    if not summary or not summary.strip():
        return {"pass": False, "reasons": ["总结为空"]}
    if len(summary) > MAX_SUMMARY_LEN:
        reasons.append(f"总结过长（{len(summary)} > {MAX_SUMMARY_LEN}）")

    low = summary.lower()
    for marker in PLACEHOLDER_MARKERS:
        if marker in low:
            reasons.append(f"含占位/编造标记：{marker}")
            break

    known = _known_numbers(metrics)
    for tok in _NUM_RE.findall(summary):
        try:
            value = float(tok.replace(",", ""))
        except ValueError:
            continue
        # 只查金额型数字（绝对值≥100 或含小数），Top5/小整数不误报
        is_amount = abs(value) >= 100 or "." in tok
        if is_amount and not _matches_known(value, known):
            reasons.append(f"疑似编造数字：{tok}")
            break

    return {"pass": not reasons, "reasons": reasons}
