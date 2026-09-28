"""verify_metrics（s17 目标闭环）：独立重算核对。

不调用主计算函数 compute.compute_all，而是用独立的数值转换与累加逻辑重新推导每个指标，
这样不仅能发现结果被篡改，也能发现主计算公式自身写错。
"""
from __future__ import annotations

import pandas as pd

from ..schemas import WorkmateError


def _close(a, b, rel: float = 1e-9, abs_tol: float = 1e-6) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        fa, fb = float(a), float(b)
        return abs(fa - fb) <= max(abs_tol, rel * max(abs(fa), abs(fb)))
    except (TypeError, ValueError):
        return a == b


def _list_close(a: list, b: list) -> bool:
    """按 name 比对（不依赖顺序）。"""
    da = {x["name"]: x.get("sales", x.get("share")) for x in a}
    db = {y["name"]: y.get("sales", y.get("share")) for y in b}
    if set(da) != set(db):
        return False
    return all(_close(da[k], db[k]) for k in da)


def _to_numeric_independent(df: pd.DataFrame, col) -> pd.Series:
    """独立于主路径的数值转换：非空但无法解析 → 报错（与主路径同语义）。"""
    raw = df[col]
    out = []
    for v in raw:
        if v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and v.strip() == ""):
            out.append(float("nan"))
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError) as e:
            raise WorkmateError("BAD_SALES_VALUE", "销售额列有无法解析的值。") from e
    return pd.Series(out, index=raw.index)


def _week_sunday(d) -> pd.Timestamp:
    """与主路径 to_period('W')（W-SUN）一致的周键：该周周日。"""
    return d + pd.Timedelta(days=6 - d.dayofweek)


def _independent_mom(df: pd.DataFrame, mapping: dict, numeric: pd.Series) -> float | None:
    date_col = mapping.get("date")
    if not date_col:
        return None
    weekly: dict = {}
    for date_val, sales_val in zip(df[date_col].tolist(), numeric.tolist()):
        if pd.isna(sales_val):
            continue
        d = pd.to_datetime(date_val, errors="coerce")
        if pd.isna(d):
            continue
        key = _week_sunday(d)
        weekly[key] = weekly.get(key, 0.0) + float(sales_val)
    if len(weekly) < 2:
        return None
    keys = sorted(weekly)
    last, prev = weekly[keys[-1]], weekly[keys[-2]]
    if prev == 0:
        return None
    return (last - prev) / prev


def _independent_top5(df: pd.DataFrame, mapping: dict, numeric: pd.Series) -> list[dict]:
    product_col = mapping.get("product")
    if not product_col:
        return []
    acc: dict[str, float] = {}
    for prod, sales_val in zip(df[product_col].tolist(), numeric.tolist()):
        name = str(prod)
        if name not in acc:
            acc[name] = 0.0
        if not pd.isna(sales_val):
            acc[name] += float(sales_val)
    items = sorted(acc.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return [{"name": k, "sales": v} for k, v in items]


def _independent_channel(df: pd.DataFrame, mapping: dict, numeric: pd.Series, total_sales: float) -> list[dict]:
    channel_col = mapping.get("channel")
    if not channel_col:
        return []
    acc: dict[str, float] = {}
    for ch, sales_val in zip(df[channel_col].tolist(), numeric.tolist()):
        name = str(ch)
        if name not in acc:
            acc[name] = 0.0
        if not pd.isna(sales_val):
            acc[name] += float(sales_val)
    if not total_sales:
        return []
    return [{"name": k, "share": v / total_sales} for k, v in acc.items()]


def _independent_recompute(df: pd.DataFrame, mapping: dict) -> dict:
    sales_col = mapping["sales"]
    numeric = _to_numeric_independent(df, sales_col)
    valid_vals = [float(x) for x in numeric.tolist() if not pd.isna(x)]
    if not valid_vals:
        raise WorkmateError("BAD_SALES_VALUE", "销售额列没有可用的数值。")

    total_sales = float(sum(valid_vals))  # Python 原生 sum，区别于 pandas .sum()
    line_count = int(len(df))

    order_count = None
    order_col = mapping.get("order")
    if order_col:
        ids: list[str] = []
        missing = False
        for x in df[order_col].tolist():
            if x is None or (isinstance(x, float) and pd.isna(x)):
                missing = True
                break
            s = str(x).strip()
            if s == "":
                missing = True
                break
            ids.append(s)
        if not missing:
            order_count = len(set(ids))  # set 去重，区别于 .nunique()

    avg_order_value = (total_sales / order_count) if order_count else None

    return {
        "total_sales": total_sales,
        "line_count": line_count,
        "order_count": order_count,
        "avg_order_value": avg_order_value,
        "mom_growth": _independent_mom(df, mapping, numeric),
        "top5": _independent_top5(df, mapping, numeric),
        "channel_share": _independent_channel(df, mapping, numeric, total_sales),
    }


def verify_metrics(df: pd.DataFrame, mapping: dict, metrics: dict) -> list[dict]:
    """独立重算并与给定 metrics 逐项比对，返回不一致清单（空 = 通过）。"""
    recomputed = _independent_recompute(df, mapping)
    issues: list[dict] = []
    for key in ["total_sales", "line_count", "order_count", "avg_order_value", "mom_growth"]:
        if not _close(metrics.get(key), recomputed.get(key)):
            issues.append({"metric": key, "expected": recomputed.get(key), "got": metrics.get(key)})
    if not _list_close(metrics.get("top5") or [], recomputed.get("top5") or []):
        issues.append({"metric": "top5", "expected": recomputed.get("top5"), "got": metrics.get("top5")})
    if not _list_close(metrics.get("channel_share") or [], recomputed.get("channel_share") or []):
        issues.append({"metric": "channel_share", "expected": recomputed.get("channel_share"), "got": metrics.get("channel_share")})
    return issues
