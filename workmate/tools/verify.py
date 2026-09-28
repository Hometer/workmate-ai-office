"""verify_metrics（s17 目标闭环）：独立重算核对，数字不一致即失败。"""
from __future__ import annotations

import pandas as pd

from . import compute

TOL = 1e-6


def _close(a, b) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= TOL
    except (TypeError, ValueError):
        return a == b


def _list_close(a: list, b: list) -> bool:
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x.get("name") != y.get("name"):
            return False
        if not _close(x.get("sales", x.get("share")), y.get("sales", y.get("share"))):
            return False
    return True


def verify_metrics(df: pd.DataFrame, mapping: dict, metrics: dict) -> list[dict]:
    """重新读源数据→独立重算→逐项比对，返回不一致清单（空 = 通过）。"""
    recomputed = compute.compute_all(df, mapping)
    issues: list[dict] = []
    for key in ["total_sales", "line_count", "order_count", "avg_order_value", "mom_growth"]:
        if not _close(metrics.get(key), recomputed.get(key)):
            issues.append({"metric": key, "expected": recomputed.get(key), "got": metrics.get(key)})
    if not _list_close(metrics.get("top5") or [], recomputed.get("top5") or []):
        issues.append({"metric": "top5", "expected": recomputed.get("top5"), "got": metrics.get("top5")})
    if not _list_close(metrics.get("channel_share") or [], recomputed.get("channel_share") or []):
        issues.append({"metric": "channel_share", "expected": recomputed.get("channel_share"), "got": metrics.get("channel_share")})
    return issues
