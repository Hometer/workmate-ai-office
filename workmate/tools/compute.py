"""compute_metrics：本地确定性计算（A/B 金额口径 + 自然周）。"""
from __future__ import annotations

import pandas as pd
import math

from ..schemas import WorkmateError
from .. import amounts, weeks

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
    for c, low in zip(columns, lowers):
        if low in [n.lower() for n in names]:
            return c
    for c, low in zip(columns, lowers):
        for n in names:
            if n.lower() in low and low:
                return c
    return None


def infer_columns(df: pd.DataFrame) -> dict:
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


def _to_numeric_sales(df: pd.DataFrame, sales_col) -> pd.Series:
    """把销售额列转数值；空值与无法解析的值都显式阻断，不悄悄忽略。"""
    raw = df[sales_col]
    numeric = pd.to_numeric(raw, errors="coerce")
    empty = raw.isna() | (raw.astype(str).str.strip() == "")
    unparseable = (~empty) & numeric.isna()
    if int(empty.sum()) > 0:
        raise WorkmateError("BAD_SALES_VALUE", f"销售额列有 {int(empty.sum())} 个空值，请补齐或删除这些行。")
    if unparseable.any():
        count = int(unparseable.sum())
        raise WorkmateError("BAD_SALES_VALUE", f"销售额列有 {count} 个无法解析的值，请清理后重试。")
    if not numeric.map(math.isfinite).all():
        raise WorkmateError("BAD_SALES_VALUE", "销售额列有非有限数值，请清理后重试。")
    if int(numeric.notna().sum()) == 0:
        raise WorkmateError("BAD_SALES_VALUE", "销售额列没有可用的数值。")
    return numeric


def _mom_from_series(dates: pd.Series, amounts: pd.Series) -> float | None:
    """按自然周（周一）聚合，环比 = (本周 − 上周) ÷ 上周。"""
    weekly: dict = {}
    for d, a in zip(dates.tolist(), amounts.tolist()):
        if pd.isna(d) or pd.isna(a):
            continue
        ts = pd.Timestamp(d)
        key = weeks.monday_of(ts.date())
        weekly[key] = weekly.get(key, 0.0) + float(a)
    if len(weekly) < 2:
        return None
    keys = sorted(weekly)
    last, prev = weekly[keys[-1]], weekly[keys[-2]]
    if prev == 0:
        return None
    return (last - prev) / prev


def compute_all(df: pd.DataFrame, mapping: dict, amount_mode: str = "A", report_week_monday=None) -> dict:
    sales_col = mapping["sales"]
    df = df.copy()

    # 报告周过滤（自然周）
    if report_week_monday and mapping.get("date"):
        df = weeks.filter_to_week(df, mapping["date"], report_week_monday)

    numeric = _to_numeric_sales(df, sales_col)
    df[sales_col] = numeric

    total_sales, amount_warnings = amounts.total_by_mode(df, mapping, amount_mode, numeric)

    line_count = int(len(df))

    order_count = None
    order_col = mapping.get("order")
    if order_col:
        ids = amounts.order_ids(df, order_col)
        if amounts.order_complete(ids):
            order_count = int(ids.nunique())

    avg_order_value = (total_sales / order_count) if order_count else None

    # 环比
    mom_growth = None
    if mapping.get("date"):
        if amount_mode == "A":
            d = pd.to_datetime(df[mapping["date"]], errors="coerce")
            mom_growth = _mom_from_series(d, df[sales_col])
        else:
            ol = amounts.order_level(df, mapping, numeric)
            if "_date" in ol.columns and not ol["_multi_date"].any():
                d = pd.to_datetime(ol["_date"], errors="coerce")
                mom_growth = _mom_from_series(d, ol["_amt"])

    # Top5 商品（仅 A 模式可可靠分摊）
    top5: list[dict] = []
    product_ranking_available = True
    product_col = mapping.get("product")
    if product_col and amount_mode == "A":
        g = df.groupby(product_col)[sales_col].sum().nlargest(5)
        top5 = [{"name": str(k), "sales": float(v)} for k, v in g.items()]
    elif product_col and amount_mode == "B":
        product_ranking_available = False

    channel_share, channel_share_available = amounts.channel_share_by_mode(df, mapping, amount_mode, numeric, total_sales)

    return {
        "total_sales": total_sales,
        "line_count": line_count,
        "order_count": order_count,
        "avg_order_value": avg_order_value,
        "mom_growth": mom_growth,
        "top5": top5,
        "channel_share": channel_share,
        "amount_mode": amount_mode,
        "report_week": str(report_week_monday) if report_week_monday else None,
        "warnings": amount_warnings,
        "product_ranking_available": product_ranking_available,
        "channel_share_available": channel_share_available,
    }
