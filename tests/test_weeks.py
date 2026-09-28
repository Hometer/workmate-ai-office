from datetime import date

import pandas as pd

from workmate import weeks


def test_monday_of():
    assert weeks.monday_of(date(2026, 9, 14)) == date(2026, 9, 14)  # 周一
    assert weeks.monday_of(date(2026, 9, 16)) == date(2026, 9, 14)  # 周三


def test_previous_week():
    assert weeks.previous_week(date(2026, 9, 14)) == date(2026, 9, 7)


def test_filter_to_week_excludes_next_monday():
    df = pd.DataFrame({"日期": ["2026-09-14", "2026-09-15", "2026-09-20", "2026-09-21"], "销售额": [1, 2, 3, 4]})
    out = weeks.filter_to_week(df, "日期", date(2026, 9, 14))
    assert len(out) == 3  # 09-21 是下周一，被排除


def test_parse_monday():
    assert weeks.parse_monday("2026-09-16") == date(2026, 9, 14)
