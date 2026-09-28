import pandas as pd
import pytest

from workmate.knowledge.report_templates import render_report
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
    assert m["line_count"] == 6
    assert m["order_count"] == 6
    assert m["avg_order_value"] == pytest.approx(920.0 / 6)
    assert m["mom_growth"] == pytest.approx(1.1, abs=1e-6)
    assert [i["name"] for i in m["top5"]] == ["香蕉", "苹果", "橙子"]
    assert m["top5"][0]["sales"] == 500.0
    shares = {i["name"]: i["share"] for i in m["channel_share"]}
    assert shares["线上"] == pytest.approx(420 / 920, abs=1e-6)
    assert shares["线下"] == pytest.approx(500 / 920, abs=1e-6)


def test_order_and_detail_counts_are_distinct():
    df = pd.DataFrame({"订单号": [" A001 ", "A001", "A002", "A003"], "销售额": [50, 30, 120, 100]})
    m = compute.compute_all(df, compute.infer_columns(df))
    assert m["total_sales"] == 300
    assert m["line_count"] == 4
    assert m["order_count"] == 3
    assert m["avg_order_value"] == 100


@pytest.mark.parametrize("order_ids", [None, ["A001", "", "A002"]])
def test_order_count_is_unknown_without_complete_ids(order_ids):
    data = {"销售额": [50, 30, 120]}
    if order_ids is not None:
        data["订单号"] = order_ids
    df = pd.DataFrame(data)
    m = compute.compute_all(df, compute.infer_columns(df))
    assert m["line_count"] == 3
    assert m["order_count"] is None
    assert m["avg_order_value"] is None
    report = render_report(m, "按已知数据汇总。")
    assert "明细行数：3" in report
    assert "订单量（订单号去重）：待确认" in report
    assert "客单价：待确认" in report


def test_bad_sales_value_raises():
    df = pd.DataFrame({"销售额": [100, "abc", 200]})
    with pytest.raises(WorkmateError) as ei:
        compute.compute_all(df, {"sales": "销售额"})
    assert ei.value.code == "BAD_SALES_VALUE"


def test_empty_sales_cells_ok():
    df = pd.DataFrame({"销售额": [100, None, 200]})
    m = compute.compute_all(df, {"sales": "销售额"})
    assert m["total_sales"] == 300.0
    assert m["line_count"] == 3
