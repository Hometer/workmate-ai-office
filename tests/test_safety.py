from workmate.tools import compute, safety


def _metrics(sample_df):
    return compute.compute_all(sample_df, compute.infer_columns(sample_df))


def test_safety_passes_clean(sample_df):
    m = _metrics(sample_df)
    summary = "本周总销售额 920.00 元，环比增长 110.00%，Top5 商品为香蕉、苹果。"
    assert safety.safety_check(summary, m)["pass"]


def test_safety_rejects_fabricated_amount(sample_df):
    m = _metrics(sample_df)
    summary = "本周总销售额 25000.00 元。"
    assert not safety.safety_check(summary, m)["pass"]


def test_safety_rejects_empty():
    assert not safety.safety_check("", {})["pass"]


def test_safety_rejects_placeholder(sample_df):
    m = _metrics(sample_df)
    assert not safety.safety_check("这是 mock 总结", m)["pass"]


def test_safety_small_ints_not_flagged(sample_df):
    m = _metrics(sample_df)
    summary = "Top5 商品共 5 个，渠道有 3 个。"
    assert safety.safety_check(summary, m)["pass"]


def test_safety_rejects_too_long(sample_df):
    m = _metrics(sample_df)
    assert not safety.safety_check("好" * 900, m)["pass"]
