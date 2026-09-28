import pandas as pd
import pytest

from workmate.schemas import WorkmateError
from workmate.tools import compute


def test_infer_columns(sample_df):
    mapping = compute.infer_columns(sample_df)
    assert mapping["sales"] == "销售额"
    assert mapping["date"] == "日期"
    assert mapping["product"] == "商品"
    assert mapping["channel"] == "渠道"
    assert mapping["order"] == "订单号"


def test_infer_columns_missing_sales():
    df = pd.DataFrame({"备注": ["x"], "其他": [1]})
    with pytest.raises(WorkmateError) as ei:
        compute.infer_columns(df)
    assert ei.value.code == "COLUMN_UNKNOWN"


def test_compute_all_numbers(sample_df):
    m = compute.compute_all(sample_df, compute.infer_columns(sample_df))
    assert m["total_sales"] == 920.0
    assert m["order_count"] == 6
    assert m["avg_order_value"] == pytest.approx(920.0 / 6)
    assert m["mom_growth"] == pytest.approx(1.1, abs=1e-6)
    assert [i["name"] for i in m["top5"]] == ["香蕉", "苹果", "橙子"]
    assert m["top5"][0]["sales"] == 500.0
    shares = {i["name"]: i["share"] for i in m["channel_share"]}
    assert shares["线上"] == pytest.approx(420 / 920, abs=1e-6)
    assert shares["线下"] == pytest.approx(500 / 920, abs=1e-6)
