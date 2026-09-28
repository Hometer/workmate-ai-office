from workmate.tools import compute, verify


def test_verify_passes(sample_df):
    mapping = compute.infer_columns(sample_df)
    metrics = compute.compute_all(sample_df, mapping)
    assert verify.verify_metrics(sample_df, mapping, metrics) == []


def test_verify_detects_tampered_total(sample_df):
    mapping = compute.infer_columns(sample_df)
    metrics = compute.compute_all(sample_df, mapping)
    metrics["total_sales"] = 99999.0
    issues = verify.verify_metrics(sample_df, mapping, metrics)
    assert any(i["metric"] == "total_sales" for i in issues)


def test_verify_detects_tampered_top5(sample_df):
    mapping = compute.infer_columns(sample_df)
    metrics = compute.compute_all(sample_df, mapping)
    metrics["top5"] = [{"name": "伪造", "sales": 1.0}]
    issues = verify.verify_metrics(sample_df, mapping, metrics)
    assert any(i["metric"] == "top5" for i in issues)


def test_verify_detects_tampered_channel(sample_df):
    mapping = compute.infer_columns(sample_df)
    metrics = compute.compute_all(sample_df, mapping)
    metrics["channel_share"] = [{"name": "线上", "share": 0.99}]
    issues = verify.verify_metrics(sample_df, mapping, metrics)
    assert any(i["metric"] == "channel_share" for i in issues)


def test_verify_independent_of_main_compute(sample_df, monkeypatch):
    mapping = compute.infer_columns(sample_df)
    metrics = compute.compute_all(sample_df, mapping)
    # 把主计算函数"弄坏"：verify 若依赖它，会误判
    monkeypatch.setattr(compute, "compute_all", lambda *a, **k: {**metrics, "total_sales": 99999.0})
    # 独立重算：正确 metrics 应通过
    assert verify.verify_metrics(sample_df, mapping, metrics) == []
    # 错误 metrics 应被检出
    issues = verify.verify_metrics(sample_df, mapping, {**metrics, "total_sales": 99999.0})
    assert any(i["metric"] == "total_sales" for i in issues)
