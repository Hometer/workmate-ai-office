"""verify_metrics（s17 目标闭环）：独立重算核对。

不调用主计算函数，用独立数值转换、累加与去重逻辑重新推导每个指标，
支持 A/B 金额口径与自然周过滤。
"""
from __future__ import annotations

import pandas as pd

from ..schemas import WorkmateError
from .. import weeks


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
    da = {x["name"]: x.get("sales", x.get("share")) for x in a}
    db = {y["name"]: y.get("sales", y.get("share")) for y in b}
    if set(da) != set(db):
        return False
    return all(_close(da[k], db[k]) for k in da)


def _to_numeric_independent(df: pd.DataFrame, col) -> pd.Series:
    raw = df[col]
    out = []
    empty_count = 0
    for v in raw:
        if v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and v.strip() == ""):
            empty_count += 1
            out.append(float("nan"))
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError) as e:
            raise WorkmateError("BAD_SALES_VALUE", "销售额列有无法解析的值。") from e
    if empty_count:
        raise WorkmateError("BAD_SALES_VALUE", f"销售额列有 {empty_count} 个空值。")
    return pd.Series(out, index=raw.index)


def _filter_week_independent(df: pd.DataFrame, date_col, monday) -> pd.DataFrame:
    start = pd.Timestamp(monday)
    end = start + pd.Timedelta(days=7)
    d = pd.to_datetime(df[date_col], errors="coerce")
    return df.loc[(d >= start) & (d < end)].copy()


def _mom_from_pairs(dates: list, amounts: list) -> float | None:
    weekly: dict = {}
    for dv, av in zip(dates, amounts):
        if dv is None or av is None or pd.isna(dv) or pd.isna(av):
            continue
        key = weeks.monday_of(pd.Timestamp(dv).date())
        weekly[key] = weekly.get(key, 0.0) + float(av)
    if len(weekly) < 2:
        return None
    keys = sorted(weekly)
    last, prev = weekly[keys[-1]], weekly[keys[-2]]
    if prev == 0:
        return None
    return (last - prev) / prev


def _independent_recompute(df: pd.DataFrame, mapping: dict, amount_mode: str, report_week_monday=None) -> dict:
    sales_col = mapping["sales"]
    if report_week_monday and mapping.get("date"):
        df = _filter_week_independent(df, mapping["date"], report_week_monday)

    numeric = _to_numeric_independent(df, sales_col)
    valid_vals = [float(x) for x in numeric.tolist() if not pd.isna(x)]
    if not valid_vals:
        raise WorkmateError("BAD_SALES_VALUE", "销售额列没有可用的数值。")

    # 总销售额（独立）
    if amount_mode == "A":
        total_sales = float(sum(valid_vals))
    else:
        total_sales = _total_b_independent(df, mapping, numeric)

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
            order_count = len(set(ids))

    avg_order_value = (total_sales / order_count) if order_count else None

    mom = _independent_mom(df, mapping, numeric, amount_mode)
    top5 = _independent_top5(df, mapping, numeric, amount_mode)
    channel = _independent_channel(df, mapping, numeric, amount_mode, total_sales)

    return {
        "total_sales": total_sales,
        "line_count": line_count,
        "order_count": order_count,
        "avg_order_value": avg_order_value,
        "mom_growth": mom,
        "top5": top5,
        "channel_share": channel,
    }


def _total_b_independent(df: pd.DataFrame, mapping: dict, numeric: pd.Series) -> float:
    order_col = mapping.get("order")
    if not order_col:
        raise WorkmateError("B_REQUIRES_ORDER_ID", "金额口径 B 需要每行都有完整订单号。")
    seen: dict[str, float] = {}
    conflict = 0
    for oid, amt in zip(df[order_col].tolist(), numeric.tolist()):
        if oid is None or (isinstance(oid, float) and pd.isna(oid)):
            raise WorkmateError("B_REQUIRES_ORDER_ID", "金额口径 B 需要每行都有完整订单号。")
        s = str(oid).strip()
        if s == "":
            raise WorkmateError("B_REQUIRES_ORDER_ID", "金额口径 B 需要每行都有完整订单号。")
        if pd.isna(amt):
            continue
        val = float(amt)
        if s in seen and seen[s] != val:
            conflict += 1
        seen[s] = val
    if conflict:
        raise WorkmateError("ORDER_AMOUNT_CONFLICT", f"有 {conflict} 个订单号存在多行金额不一致。")
    return float(sum(seen.values()))


def _order_level_independent(df: pd.DataFrame, mapping: dict, numeric: pd.Series) -> dict:
    """返回 {amount, dates:set, channels:set} 的订单级字典。"""
    order_col = mapping["order"]
    date_col = mapping.get("date")
    channel_col = mapping.get("channel")
    amt: dict[str, float] = {}
    dates: dict[str, set] = {}
    channels: dict[str, set] = {}
    for i in range(len(df)):
        oid = str(df[order_col].iloc[i]).strip()
        if oid not in amt:
            amt[oid] = float(numeric.iloc[i]) if not pd.isna(numeric.iloc[i]) else 0.0
        if date_col:
            dv = pd.to_datetime(df[date_col].iloc[i], errors="coerce")
            if not pd.isna(dv):
                dates.setdefault(oid, set()).add(dv.date())
        if channel_col:
            channels.setdefault(oid, set()).add(str(df[channel_col].iloc[i]))
    return {"amount": amt, "dates": dates, "channels": channels}


def _independent_mom(df: pd.DataFrame, mapping: dict, numeric: pd.Series, amount_mode: str) -> float | None:
    date_col = mapping.get("date")
    if not date_col:
        return None
    if amount_mode == "A":
        dates = pd.to_datetime(df[date_col], errors="coerce").tolist()
        return _mom_from_pairs(dates, numeric.tolist())
    ol = _order_level_independent(df, mapping, numeric)
    if any(len(s) > 1 for s in ol["dates"].values()):
        return None
    pairs_dates = [list(s)[0] for s in ol["dates"].values()]
    pairs_amt = [ol["amount"][o] for o in ol["dates"]]
    return _mom_from_pairs(pairs_dates, pairs_amt)


def _independent_top5(df: pd.DataFrame, mapping: dict, numeric: pd.Series, amount_mode: str) -> list[dict]:
    product_col = mapping.get("product")
    if not product_col or amount_mode == "B":
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


def _independent_channel(df: pd.DataFrame, mapping: dict, numeric: pd.Series, amount_mode: str, total_sales: float) -> list[dict]:
    channel_col = mapping.get("channel")
    if not channel_col:
        return []
    acc: dict[str, float] = {}
    if amount_mode == "A":
        for ch, sales_val in zip(df[channel_col].tolist(), numeric.tolist()):
            name = str(ch)
            if name not in acc:
                acc[name] = 0.0
            if not pd.isna(sales_val):
                acc[name] += float(sales_val)
    else:
        ol = _order_level_independent(df, mapping, numeric)
        if any(len(s) > 1 for s in ol["channels"].values()):
            return []
        for oid, chs in ol["channels"].items():
            name = list(chs)[0]
            acc[name] = acc.get(name, 0.0) + ol["amount"][oid]
    if not total_sales or any(v < 0 for v in acc.values()):
        return []
    return [{"name": k, "share": v / total_sales} for k, v in acc.items()]


def verify_metrics(df: pd.DataFrame, mapping: dict, metrics: dict, amount_mode: str = "A", report_week_monday=None) -> list[dict]:
    recomputed = _independent_recompute(df, mapping, amount_mode, report_week_monday)
    issues: list[dict] = []
    for key in ["total_sales", "line_count", "order_count", "avg_order_value"]:
        if not _close(metrics.get(key), recomputed.get(key)):
            issues.append({"metric": key, "expected": recomputed.get(key), "got": metrics.get(key)})
    if not _list_close(metrics.get("top5") or [], recomputed.get("top5") or []):
        issues.append({"metric": "top5", "expected": recomputed.get("top5"), "got": metrics.get("top5")})
    if not _list_close(metrics.get("channel_share") or [], recomputed.get("channel_share") or []):
        issues.append({"metric": "channel_share", "expected": recomputed.get("channel_share"), "got": metrics.get("channel_share")})
    return issues
