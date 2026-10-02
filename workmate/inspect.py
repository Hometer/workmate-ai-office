"""数据检查（PRD v0.6 F1）：全表质量、字段映射建议（含歧义）、PII 识别、周覆盖、币种检测、阻断项。"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from . import weeks
from .tools import compute, files
from .schemas import WorkmateError

PII_HINTS = [
    "姓名", "电话", "手机", "邮箱", "邮件", "地址", "身份证", "客户", "联系", "联系人",
    "name", "phone", "email", "address", "mobile", "tel", "contact",
]
CURRENCY_HINTS = ["币种", "货币", "currency", "ccy"]


def file_fingerprint(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_pii_columns(columns) -> list[str]:
    return [str(c) for c in columns if any(hint in str(c).lower() for hint in PII_HINTS)]


def detect_currency(df: pd.DataFrame) -> tuple[str | None, int]:
    for c in df.columns:
        if any(hint in str(c).lower() for hint in CURRENCY_HINTS):
            return str(c), int(df[c].astype(str).nunique())
    return None, 0


def currency_display_unit(df: pd.DataFrame) -> str | None:
    """返回识别到的单一币种显示单位；无币种列或无单一值返回 None（不默认元）。"""
    col, distinct = detect_currency(df)
    if col is None or distinct == 0:
        return None
    vals = df[col].astype(str).str.strip().unique().tolist()
    if len(vals) == 1:
        low = vals[0].lower()
        if low in ("cny", "rmb", "人民币", "¥", "元"):
            return "元"
        return vals[0]
    return None


def _clean_val(v):
    try:
        if v is None or pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def _safe_records(df: pd.DataFrame, limit: int) -> list[dict]:
    records = []
    for _, row in df.head(limit).iterrows():
        rec = {str(k): _clean_val(v) for k, v in row.items()}
        records.append(rec)
    return records


def _match_columns(df: pd.DataFrame, names: list[str]) -> list:
    columns = list(df.columns)
    lowers = [str(c).strip().lower() for c in columns]
    exact = [c for c, low in zip(columns, lowers) if low in [n.lower() for n in names]]
    if exact:
        return exact
    return [c for c, low in zip(columns, lowers) if any(n.lower() in low and low for n in names)]


def suggest_mapping(df: pd.DataFrame) -> tuple[dict, list[str]]:
    mapping: dict = {}
    ambiguities: list[str] = []
    for key, names in compute.COLUMN_ALIASES.items():
        cols = _match_columns(df, names)
        if len(cols) == 1:
            mapping[key] = cols[0]
        elif len(cols) > 1:
            mapping[key] = None
            ambiguities.append(f"“{key}”有多个候选列：{'、'.join(str(c) for c in cols)}，请手动确认")
    return mapping, ambiguities


def validate_mapping(df: pd.DataFrame, mapping: dict) -> dict:
    """检查业务字段与列名，错误不回显传入值；空选填字段保留未指定语义。"""
    if not isinstance(mapping, dict):
        raise WorkmateError("FIELD_MAPPING_INVALID", "字段选择无效，请重新检查并选择当前表格中存在的列。")
    validated = {}
    for key, value in mapping.items():
        if key not in compute.COLUMN_ALIASES:
            raise WorkmateError("FIELD_MAPPING_INVALID", "字段选择无效，请重新检查并选择当前表格中存在的列。")
        if value is None or (isinstance(value, str) and value == ""):
            continue
        if not isinstance(value, str) or value not in df.columns:
            raise WorkmateError("FIELD_MAPPING_INVALID", "字段选择无效，请重新检查并选择当前表格中存在的列。")
        validated[key] = value
    return validated


def quality_summary(df: pd.DataFrame, mapping: dict) -> dict:
    q: dict = {}
    sales_col = mapping.get("sales")
    if sales_col:
        raw = df[sales_col]
        numeric = pd.to_numeric(raw, errors="coerce")
        empty = raw.isna() | (raw.astype(str).str.strip() == "")
        unparseable = (~empty) & numeric.isna()
        q["sales"] = {
            "valid": int((~empty & ~unparseable).sum()),
            "empty": int(empty.sum()),
            "unparseable": int(unparseable.sum()),
        }
    date_col = mapping.get("date")
    if date_col:
        d = pd.to_datetime(df[date_col], errors="coerce")
        empty = df[date_col].isna() | (df[date_col].astype(str).str.strip() == "")
        unparseable = (~empty) & d.isna()
        q["date"] = {
            "valid": int((~empty & ~unparseable).sum()),
            "empty": int(empty.sum()),
            "unparseable": int(unparseable.sum()),
        }
    order_col = mapping.get("order")
    if order_col:
        ids = df[order_col].astype("string").str.strip()
        nonempty = ids.notna() & ids.ne("")
        total = int(nonempty.sum())
        unique = int(ids[nonempty].nunique())
        q["order_complete_rate"] = round(total / len(df), 4) if len(df) else 0.0
        q["duplicate_orders"] = total - unique
    return q


def blockers(df: pd.DataFrame, mapping: dict, quality: dict, amount_mode) -> list[str]:
    b: list[str] = []
    if len(df) == 0:
        b.append("表格为空")
    if not mapping.get("sales"):
        b.append("缺少销售额列")
    else:
        s = quality.get("sales", {})
        if s.get("empty", 0) > 0:
            b.append(f"销售额列有 {s['empty']} 个空值")
        if s.get("unparseable", 0) > 0:
            b.append(f"销售额列有 {s['unparseable']} 个无法解析的值")
        elif s.get("valid", 0) == 0:
            b.append("销售额列没有有效数值")
    if amount_mode is None and mapping.get("sales"):
        b.append("金额口径未确认")
    currency_col, currency_distinct = detect_currency(df)
    if currency_distinct > 1:
        b.append(f"币种列（{currency_col}）有 {currency_distinct} 种币种，不能混算")
    return b


def preview(df: pd.DataFrame, mapping: dict, pii_columns: list[str], limit: int = 5) -> list[dict]:
    """白名单：仅输出已映射且非 PII 的列；映射失败返回空预览，绝不回退全列。"""
    cols = [c for c in mapping.values() if c is not None and c not in pii_columns]
    if not cols:
        return []
    return _safe_records(df[cols], limit)


def week_stats(df: pd.DataFrame, date_col, weeks_list: list) -> list[dict]:
    d = pd.to_datetime(df[date_col], errors="coerce")
    out = []
    for w in weeks_list:
        start = pd.Timestamp(w)
        end = start + pd.Timedelta(days=7)
        in_week = (d >= start) & (d < end)
        out.append({
            "monday": str(w),
            "valid_rows": int(in_week.sum()),
            "days_with_data": int(d[in_week].dt.date.nunique()),
        })
    return out


def inspect_file(path, amount_mode=None, field_mapping=None) -> dict:
    df = files.read_table(path)
    if field_mapping is not None:
        mapping = validate_mapping(df, field_mapping)
        ambiguities: list[str] = []
    else:
        mapping, ambiguities = suggest_mapping(df)
    quality = quality_summary(df, mapping)
    pii = detect_pii_columns(df.columns)
    has_date = bool(mapping.get("date"))
    weeks_list = weeks.list_weeks(weeks.valid_dates(df, mapping["date"])) if has_date else []
    currency_col, currency_distinct = detect_currency(df)
    return {
        "summary": {
            "rows": int(len(df)),
            "columns": [str(c) for c in df.columns],
            "file_size": Path(path).stat().st_size,
            "fingerprint": file_fingerprint(path),
        },
        "mapping": mapping,
        "ambiguities": ambiguities,
        "quality": quality,
        "pii_columns": pii,
        "preview": preview(df, mapping, pii),
        "blockers": blockers(df, mapping, quality, amount_mode),
        "weeks": [str(w) for w in weeks_list],
        "week_stats": week_stats(df, mapping["date"], weeks_list) if has_date else [],
        "has_date": has_date,
        "currency": {"column": currency_col, "distinct": currency_distinct, "unit": currency_display_unit(df)},
    }
