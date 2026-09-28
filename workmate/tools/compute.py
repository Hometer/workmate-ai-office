"""compute_metrics：本地确定性计算（pandas），不让模型心算，从根上避免数字幻觉。"""
from __future__ import annotations

import pandas as pd

from ..schemas import WorkmateError

# 列名别名（常见中文/英文字段），大小写不敏感
COLUMN_ALIASES = {
    "sales": ["销售额", "销售金额", "金额", "成交额", "销售额(元)", "sales", "amount", "revenue", "gmv"],
    "date": ["日期", "时间", "下单时间", "交易日期", "日期时间", "date", "day"],
    "product": ["商品", "产品", "商品名称", "产品名称", "品名", "product", "sku", "goods"],
    "channel": ["渠道", "来源", "渠道名称", "平台", "channel", "source"],
    "order": ["订单号", "订单", "流水号", "订单编号", "流水", "order_id", "orderid"],
}


def _find_column(df: pd.DataFrame, names: list[str]):
    columns = list(df.columns)
    lowers = [str(c).strip().lower() for c in columns]
    # 精确匹配优先
    for c, low in zip(columns, lowers):
        if low in [n.lower() for n in names]:
            return c
    # 再尝试"包含"
    for c, low in zip(columns, lowers):
        for n in names:
            if n.lower() in low and low:
                return c
    return None


def infer_columns(df: pd.DataFrame) -> dict:
    """自动识别业务列，返回 {sales, date, product, channel, order} 映射。"""
    mapping = {}
    for key, names in COLUMN_ALIASES.items():
        col = _find_column(df, names)
        if col is not None:
            mapping[key] = col
    if "sales" not in mapping:
        cols = "、".join(str(c) for c in df.columns)
        raise WorkmateError(
            "COLUMN_UNKNOWN",
            f"无法识别'销售额'列。当前表列名：{cols}。请把销售额列改名为：销售额/金额/sales/amount，再重试。",
        )
    return mapping


def _mom_growth(df: pd.DataFrame, date_col, sales_col) -> float | None:
    """环比增长率 = (本周 − 上周) ÷ 上周；不足两周返回 None。"""
    try:
        d = pd.to_datetime(df[date_col], errors="coerce")
        w = d.dt.to_period("W")
        mask = d.notna() & df[sales_col].notna()
        weekly = df.loc[mask].assign(_w=w[mask]).groupby("_w")[sales_col].sum().sort_index()
        if len(weekly) < 2:
            return None
        last, prev = float(weekly.iloc[-1]), float(weekly.iloc[-2])
        if prev == 0:
            return None
        return (last - prev) / prev
    except Exception:  # noqa: BLE001
        return None


def compute_all(df: pd.DataFrame, mapping: dict) -> dict:
    sales_col = mapping["sales"]
    df = df.copy()
    df[sales_col] = pd.to_numeric(df[sales_col], errors="coerce")

    total_sales = float(df[sales_col].sum())

    order_col = mapping.get("order")
    order_count = int(df[order_col].nunique()) if order_col else int(len(df))

    avg_order_value = (total_sales / order_count) if order_count else None

    mom_growth = _mom_growth(df, mapping.get("date"), sales_col) if mapping.get("date") else None

    top5 = []
    product_col = mapping.get("product")
    if product_col:
        g = df.groupby(product_col)[sales_col].sum().nlargest(5)
        top5 = [{"name": str(k), "sales": float(v)} for k, v in g.items()]

    channel_share = []
    channel_col = mapping.get("channel")
    if channel_col:
        g = df.groupby(channel_col)[sales_col].sum()
        total = float(g.sum())
        if total:
            channel_share = [{"name": str(k), "share": float(v) / total} for k, v in g.items()]

    return {
        "total_sales": total_sales,
        "order_count": order_count,
        "avg_order_value": avg_order_value,
        "mom_growth": mom_growth,
        "top5": top5,
        "channel_share": channel_share,
    }
