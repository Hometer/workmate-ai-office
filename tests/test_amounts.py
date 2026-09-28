import pandas as pd
import pytest

from workmate.schemas import WorkmateError
from workmate.tools import compute


def test_a_mode_sums_each_row():
    df = pd.DataFrame({"订单号": ["A", "A", "B"], "销售额": [100, 100, 50]})
    m = compute.compute_all(df, {"sales": "销售额", "order": "订单号"}, "A")
    assert m["total_sales"] == 250


def test_b_mode_dedups_by_order():
    df = pd.DataFrame({"订单号": ["A", "A", "B"], "销售额": [100, 100, 50]})
    m = compute.compute_all(df, {"sales": "销售额", "order": "订单号"}, "B")
    assert m["total_sales"] == 150
    assert m["order_count"] == 2
    assert m["avg_order_value"] == 75


def test_b_mode_conflict_blocks():
    df = pd.DataFrame({"订单号": ["A", "A"], "销售额": [100, 200]})
    with pytest.raises(WorkmateError) as ei:
        compute.compute_all(df, {"sales": "销售额", "order": "订单号"}, "B")
    assert ei.value.code == "ORDER_AMOUNT_CONFLICT"


def test_b_mode_requires_complete_order():
    df = pd.DataFrame({"销售额": [100, 200]})
    with pytest.raises(WorkmateError) as ei:
        compute.compute_all(df, {"sales": "销售额"}, "B")
    assert ei.value.code == "B_REQUIRES_ORDER_ID"


def test_b_mode_product_ranking_unavailable():
    df = pd.DataFrame({"订单号": ["A", "A", "B"], "商品": ["X", "Y", "Z"], "销售额": [100, 100, 50]})
    m = compute.compute_all(df, {"sales": "销售额", "order": "订单号", "product": "商品"}, "B")
    assert m["product_ranking_available"] is False
    assert m["top5"] == []
