"""金额口径（PRD v0.5 F2）：A 每行金额相加；B 整单金额去重。"""
from __future__ import annotations

import pandas as pd

from .schemas import WorkmateError


def order_ids(df: pd.DataFrame, order_col) -> pd.Series:
    """清洗后的订单号（去首尾空格）。"""
    return df[order_col].astype("string").str.strip()


def order_complete(ids: pd.Series) -> bool:
    return bool(ids.notna().all() and ids.ne("").all())


def total_by_mode(df: pd.DataFrame, mapping: dict, amount_mode: str, sales_numeric: pd.Series) -> tuple[float, list[str]]:
    """按口径计算总销售额，返回 (总额, warnings)。"""
    if amount_mode == "A":
        return float(sales_numeric.sum()), []

    order_col = mapping.get("order")
    if not order_col:
        raise WorkmateError("B_REQUIRES_ORDER_ID", "金额口径 B 需要每行都有完整订单号。")
    ids = order_ids(df, order_col)
    if not order_complete(ids):
        raise WorkmateError("B_REQUIRES_ORDER_ID", "金额口径 B 需要每行都有完整订单号，且不能有空订单号。")

    frame = df.assign(_id=ids, _amt=sales_numeric)
    grouped = frame.groupby("_id")["_amt"].agg(["nunique", "first"])
    conflict = grouped[grouped["nunique"] > 1]
    if len(conflict) > 0:
        raise WorkmateError("ORDER_AMOUNT_CONFLICT", f"有 {len(conflict)} 个订单号存在多行金额不一致，请先核对订单金额。")

    total = float(grouped["first"].sum())
    warnings: list[str] = []
    if mapping.get("date") and (frame.groupby("_id")[mapping["date"]].nunique() > 1).any():
        warnings.append("部分订单跨多个日期，相关日期趋势与周比较标为口径待确认。")
    if mapping.get("channel") and (frame.groupby("_id")[mapping["channel"]].nunique() > 1).any():
        warnings.append("部分订单跨多个渠道，渠道占比标为口径待确认。")
    return total, warnings


def order_level(df: pd.DataFrame, mapping: dict, sales_numeric: pd.Series) -> pd.DataFrame:
    """B 模式：把明细归约到订单级（每订单一行），供日期/渠道等维度汇总。"""
    ids = order_ids(df, mapping["order"])
    frame = df.assign(_id=ids, _amt=sales_numeric)
    # 每订单取第一行的日期/渠道，并记录该订单是否跨多日期/多渠道
    records = []
    for oid, g in frame.groupby("_id"):
        rec = {"_id": oid, "_amt": float(g["_amt"].iloc[0])}
        if mapping.get("date"):
            rec["_date"] = g[mapping["date"]].iloc[0]
            rec["_multi_date"] = int(g[mapping["date"]].nunique() > 1)
        if mapping.get("channel"):
            rec["_channel"] = g[mapping["channel"]].iloc[0]
            rec["_multi_channel"] = int(g[mapping["channel"]].nunique() > 1)
        records.append(rec)
    return pd.DataFrame(records)


def channel_share_by_mode(df: pd.DataFrame, mapping: dict, amount_mode: str, sales_numeric: pd.Series, total_sales: float):
    """渠道占比（口径感知）。返回 (share_list, available)。"""
    channel_col = mapping.get("channel")
    if not channel_col:
        return [], True  # 无渠道列：不影响其他结论
    if amount_mode == "A":
        g = df.groupby(channel_col).sum(numeric_only=True)
        g = g[sales_numeric.name] if sales_numeric.name in g.columns else None
        if g is None:
            return [], False
    else:
        ol = order_level(df, mapping, sales_numeric)
        if "_channel" not in ol.columns:
            return [], False
        if ol["_multi_channel"].any():
            return [], False
        g = ol.groupby("_channel")["_amt"].sum()

    if total_sales <= 0 or (g < 0).any():
        return [], False
    return [{"name": str(k), "share": float(v) / total_sales} for k, v in g.items()], True


def daily_trend(df: pd.DataFrame, mapping: dict, sales_numeric: pd.Series, amount_mode: str):
    """按日汇总（口径感知），返回 pd.Series（index=日期, value=金额）或 None（不可用）。"""
    date_col = mapping.get("date")
    if not date_col:
        return None
    if amount_mode == "A":
        d = pd.to_datetime(df[date_col], errors="coerce")
        s = pd.Series(sales_numeric.to_numpy(dtype=float), index=d)
        s = s.dropna()
        return s.groupby(s.index).sum() if len(s) else None
    ol = order_level(df, mapping, sales_numeric)
    if "_date" not in ol.columns or ol["_multi_date"].any():
        return None
    d = pd.to_datetime(ol["_date"], errors="coerce")
    s = pd.Series(ol["_amt"].to_numpy(dtype=float), index=d).dropna()
    return s.groupby(s.index).sum() if len(s) else None
