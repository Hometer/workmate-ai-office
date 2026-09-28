from workmate import inspect


def test_inspect_sample(sample_xlsx):
    r = inspect.inspect_file(sample_xlsx)
    assert r["summary"]["rows"] == 6
    assert r["mapping"]["sales"] == "销售额"
    assert r["mapping"]["date"] == "日期"
    assert "金额口径未确认" in r["blockers"]
    assert r["has_date"] is True


def test_detect_pii_columns():
    cols = ["客户姓名", "电话", "销售额", "日期"]
    assert set(inspect.detect_pii_columns(cols)) == {"客户姓名", "电话"}


def test_unparseable_sales_reported_in_quality():
    import pandas as pd

    df = pd.DataFrame({"销售额": [1, 2, "abc"]})
    mapping, _ = inspect.suggest_mapping(df)
    q = inspect.quality_summary(df, mapping)
    assert q["sales"]["unparseable"] == 1
