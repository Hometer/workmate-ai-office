"""数据检查（PRD v0.5 F1）：全表质量、字段映射建议（含歧义）、PII 识别、阻断项。"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from . import weeks
from .tools import compute, files

PII_HINTS = [
    "姓名", "电话", "手机", "邮箱", "邮件", "地址", "身份证", "客户", "联系", "联系人",
    "name", "phone", "email", "address", "mobile", "tel", "contact",
]


def file_fingerprint(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_pii_columns(columns) -> list[str]:
    return [str(c) for c in columns if any(hint in str(c).lower() for hint in PII_HINTS)]


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
        if s.get("unparseable", 0) > 0:
            b.append(f"销售额列有 {s['unparseable']} 个无法解析的值")
        elif s.get("valid", 0) == 0:
            b.append("销售额列没有有效数值")
    if amount_mode is None and mapping.get("sales"):
        b.append("金额口径未确认")
    return b


def preview(df: pd.DataFrame, mapping: dict, pii_columns: list[str], limit: int = 5) -> list[dict]:
    cols = [c for c in mapping.values() if c is not None]
    cols = [c for c in cols if c not in pii_columns]
    if not cols:
        cols = list(df.columns)
    return df[cols].head(limit).to_dict(orient="records")


def inspect_file(path, amount_mode=None) -> dict:
    df = files.read_table(path)
    mapping, ambiguities = suggest_mapping(df)
    quality = quality_summary(df, mapping)
    pii = detect_pii_columns(df.columns)
    has_date = bool(mapping.get("date"))
    weeks_list = weeks.list_weeks(weeks.valid_dates(df, mapping["date"])) if has_date else []
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
        "has_date": has_date,
    }
