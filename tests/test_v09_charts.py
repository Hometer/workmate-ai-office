"""Verify readable, faithful charts without changing calculation eligibility."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pandas as pd
import pytest
from PIL import Image
from matplotlib.figure import Figure
from matplotlib.text import Text

from workmate.tools.plot import plot_top5, plot_trend_series, plot_channel
from workmate.tools.compute import compute_all, infer_columns


def capture(monkeypatch):
    original = Figure.savefig
    saved = []

    def save(figure, path, *args, **kwargs):
        saved.append({"path": str(path), "texts": [item.get_text() for item in figure.findobj(Text)],
                      "bar_widths": [bar.get_width() for axis in figure.axes for bar in axis.patches],
                      "lines": [(list(line.get_xdata()), list(line.get_ydata())) for axis in figure.axes for line in axis.lines]})
        return original(figure, path, *args, **kwargs)

    monkeypatch.setattr(Figure, "savefig", save)
    return saved


def test_refunds_and_long_chinese_labels_remain_visible(tmp_path, monkeypatch):
    records = capture(monkeypatch)
    values = [{"name": "中文商品名称很长时也需要完整显示并可核对", "sales": 1250.5}, {"name": "退款商品", "sales": -250.5}]
    before = deepcopy(values)
    path = tmp_path / "refund.png"
    plot_top5(values, path, context={"unit": "单位待确认", "scope": "全表", "amount_mode": "A"})
    assert values == before
    texts = "\n".join(records[0]["texts"])
    assert "-250.50" in texts and "1,250.50" in texts and "单位待确认" in texts
    assert "中文商品名称很长时也需要完整显示并可核对" in texts.replace("\n", "")
    with Image.open(path) as image:
        assert image.format == "PNG" and image.width > 1000 and image.height > 500


def test_trend_retains_signed_values_and_does_not_invent_unrecorded_days(tmp_path, monkeypatch):
    records = capture(monkeypatch)
    series = pd.Series([-50, 0, 150], index=["2026-09-28", "2026-09-30", "2026-10-02"])
    plot_trend_series(series, tmp_path / "trend.png", context={"unit": "USD", "scope": "报告周 2026-09-28 ~ 2026-10-04"})
    assert records[0]["lines"][0] == (list(series.index), [-50, 0, 150])
    assert "2026-09-29" not in records[0]["texts"]
    assert any("USD" in text for text in records[0]["texts"])


def test_zero_percentage_chart_is_a_readable_zero_without_fabricated_shares(tmp_path, monkeypatch):
    records = capture(monkeypatch)
    plot_channel([{"name": "线上", "share": 0}, {"name": "门店", "share": 0}], tmp_path / "zero.png", context={"unit": "JPY", "scope": "全表"})
    assert records[0]["texts"].count("0.00%") == 2
    assert any("金额单位：JPY" in text for text in records[0]["texts"])


def test_channel_chart_percent_matches_independently_known_sales_totals(tmp_path, monkeypatch):
    records = capture(monkeypatch)
    df = pd.DataFrame({"销售额": [125.5, 400, 74.5], "渠道": ["线上", "线上", "门店"]})
    shares = compute_all(df, infer_columns(df))["channel_share"]
    before = deepcopy(shares)
    plot_channel(shares, tmp_path / "channel.png", context={"unit": "USD", "scope": "全表"})
    assert shares == before
    assert sorted(records[0]["bar_widths"]) == pytest.approx([74.5 / 600 * 100, 525.5 / 600 * 100])
    assert "87.58%" in records[0]["texts"] and "12.42%" in records[0]["texts"]
    assert "0.88%" not in records[0]["texts"]


def test_concurrent_chart_contexts_do_not_leak_into_other_outputs(tmp_path, monkeypatch):
    records = capture(monkeypatch)

    def render(unit):
        plot_top5([{"name": "商品", "sales": 100}], tmp_path / f"{unit}.png", context={"unit": unit, "scope": f"{unit} 独立范围", "amount_mode": "A"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(render, ["USD", "JPY"]))
    assert len(records) == 2
    for record in records:
        unit = "USD" if record["path"].endswith("USD.png") else "JPY"
        other = "JPY" if unit == "USD" else "USD"
        texts = "\n".join(record["texts"])
        assert f"{unit} 独立范围" in texts and other not in texts
