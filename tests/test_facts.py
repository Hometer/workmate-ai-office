from workmate import facts


def test_build_facts(sample_df):
    from workmate.tools import compute

    m = compute.compute_all(sample_df, compute.infer_columns(sample_df), "A")
    cards = facts.build_facts(m, compute.infer_columns(sample_df), None, True)
    ids = {c["id"] for c in cards}
    assert "total_sales" in ids
    assert "line_count" in ids
    assert "order_count" in ids


def test_change_facts_empty_when_equal():
    r = {"total_sales": 100, "channel_share": [{"name": "线上", "share": 0.5}]}
    c = {"total_sales": 100, "channel_share": [{"name": "线上", "share": 0.5}]}
    assert facts.build_change_facts(r, c, {}) == []
