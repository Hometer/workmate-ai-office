"""自然周工具（周一 00:00 至下周一 00:00，本机时区）。"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_bounds(monday: date) -> tuple[date, date]:
    """给定周一，返回 (周一, 周日)。"""
    return monday, monday + timedelta(days=6)


def previous_week(monday: date) -> date:
    return monday - timedelta(days=7)


def list_weeks(dates: list[date]) -> list[date]:
    """有数据的自然周周一，升序去重。"""
    return sorted({monday_of(d) for d in dates})


def latest_week_with_data(dates: list[date]) -> date | None:
    weeks = list_weeks(dates)
    return weeks[-1] if weeks else None


def parse_monday(value) -> date | None:
    """把 'YYYY-MM-DD' 解析为日期，并归一化到该日所在周的周一。"""
    if not value:
        return None
    d = datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    return monday_of(d)


def filter_to_week(df: pd.DataFrame, date_col, monday: date) -> pd.DataFrame:
    """按自然周过滤：仅保留落在 [monday, monday+7) 的行。"""
    d = pd.to_datetime(df[date_col], errors="coerce")
    start = pd.Timestamp(monday)
    end = start + pd.Timedelta(days=7)
    mask = (d >= start) & (d < end)
    return df.loc[mask].copy()


def valid_dates(df: pd.DataFrame, date_col) -> list[date]:
    d = pd.to_datetime(df[date_col], errors="coerce")
    return [x.date() for x in d.dropna().tolist()]
