from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def sample_df() -> pd.DataFrame:
    data = {
        "订单号": ["A1", "A2", "A3", "A4", "A5", "A6"],
        "日期": ["2026-09-01", "2026-09-02", "2026-09-08", "2026-09-09", "2026-09-15", "2026-09-16"],
        "商品": ["苹果", "香蕉", "苹果", "橙子", "香蕉", "苹果"],
        "渠道": ["线上", "线下", "线上", "线上", "线下", "线上"],
        "销售额": [100, 200, 150, 50, 300, 120],
    }
    return pd.DataFrame(data)


@pytest.fixture
def sample_xlsx(sample_df, tmp_path: Path) -> Path:
    p = tmp_path / "sales.xlsx"
    sample_df.to_excel(p, index=False)
    return p
