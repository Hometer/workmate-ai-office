import json
from pathlib import Path

import pandas as pd
import pytest

from workmate import inspect
from workmate.config import Config
from workmate.loop import Loop
from workmate.schemas import WorkmateError


def _cfg(tmp_path: Path) -> Config:
    return Config(
        {
            "data_dir": tmp_path / "data",
            "output_dir": tmp_path / "outputs",
            "model_provider": "mock",
            "ollama_host": "http://localhost:11434",
            "ollama_model": "qwen2.5:7b",
        }
    )


def test_inspect_json_serializable_with_nan(tmp_path):
    df = pd.DataFrame({"销售额": [1.0, float("nan"), 3.0], "商品": ["A", "B", "C"]})
    p = tmp_path / "n.xlsx"
    df.to_excel(p, index=False)
    r = inspect.inspect_file(p)
    json.dumps(r)  # 不抛异常
    assert r["quality"]["sales"]["empty"] == 1


def test_preview_excludes_pii(tmp_path):
    df = pd.DataFrame({"客户姓名": ["张三"], "备注": ["x"]})
    mapping, _ = inspect.suggest_mapping(df)
    pii = inspect.detect_pii_columns(df.columns)
    assert inspect.preview(df, mapping, pii) == []


def test_amount_mode_required(tmp_path, sample_df):
    cfg = _cfg(tmp_path)
    cfg.data_dir.mkdir()
    xlsx = cfg.data_dir / "s.xlsx"
    sample_df.to_excel(xlsx, index=False)
    loop = Loop(cfg)
    with pytest.raises(WorkmateError) as ei:
        loop.run("做周报", str(xlsx))
    assert ei.value.code == "AMOUNT_MODE_REQUIRED"


def test_compare_week_must_be_adjacent(tmp_path, sample_df):
    cfg = _cfg(tmp_path)
    cfg.data_dir.mkdir()
    xlsx = cfg.data_dir / "s.xlsx"
    sample_df.to_excel(xlsx, index=False)
    loop = Loop(cfg)
    with pytest.raises(WorkmateError) as ei:
        loop.run("做周报", str(xlsx), amount_mode="A", report_week="2026-09-14", compare_week="2026-08-31")
    assert ei.value.code == "COMPARE_WEEK_INVALID"


def test_b_cross_week_no_mom(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.data_dir.mkdir()
    df = pd.DataFrame({
        "订单号": ["A", "A", "B"],
        "日期": ["2026-09-07", "2026-09-14", "2026-09-15"],
        "销售额": [100, 100, 50],
    })
    xlsx = cfg.data_dir / "s.xlsx"
    df.to_excel(xlsx, index=False)
    loop = Loop(cfg)
    with pytest.raises(WorkmateError) as ei:
        loop.run("做周报", str(xlsx), amount_mode="B", report_week="2026-09-14", complete={"report": True, "compare": True})
    assert ei.value.code == "ORDER_WEEK_AMBIGUOUS"
    assert loop.storage.list_tasks()[0].result is None  # 无环比，也不交付归属不清的周金额


def test_multi_currency_blocks(tmp_path, sample_df):
    cfg = _cfg(tmp_path)
    cfg.data_dir.mkdir()
    df = sample_df.copy()
    df["币种"] = ["CNY"] * 3 + ["USD"] * 3
    xlsx = cfg.data_dir / "s.xlsx"
    df.to_excel(xlsx, index=False)
    loop = Loop(cfg)
    with pytest.raises(WorkmateError) as ei:
        loop.run("做周报", str(xlsx), amount_mode="A")
    assert ei.value.code == "MULTI_CURRENCY"


def test_full_table_bad_amount_blocks(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.data_dir.mkdir()
    df = pd.DataFrame({"日期": ["2026-09-15", "2026-09-01"], "销售额": [100, "abc"]})
    xlsx = cfg.data_dir / "s.xlsx"
    df.to_excel(xlsx, index=False)
    loop = Loop(cfg)
    with pytest.raises(WorkmateError) as ei:
        loop.run("做周报", str(xlsx), amount_mode="A", report_week="2026-09-14")
    assert ei.value.code == "BAD_SALES_VALUE"


def test_change_facts_require_complete(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.data_dir.mkdir()
    df = pd.DataFrame({
        "日期": ["2026-09-07", "2026-09-08", "2026-09-14", "2026-09-15"],
        "渠道": ["线上", "线上", "线下", "线下"],
        "销售额": [100, 100, 50, 50],
    })
    xlsx = cfg.data_dir / "s.xlsx"
    df.to_excel(xlsx, index=False)
    loop = Loop(cfg)
    result = loop.run("做周报", str(xlsx), amount_mode="A", report_week="2026-09-14", complete={"report": False, "compare": False})
    assert result["change_facts"] == []


def test_b_multi_week_no_mom(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.data_dir.mkdir()
    df = pd.DataFrame({
        "订单号": ["A", "B", "A"],
        "日期": ["2026-09-01", "2026-09-08", "2026-09-15"],
        "销售额": [100, 50, 100],
    })
    xlsx = cfg.data_dir / "s.xlsx"
    df.to_excel(xlsx, index=False)
    loop = Loop(cfg)
    with pytest.raises(WorkmateError) as ei:
        loop.run("做周报", str(xlsx), amount_mode="B", report_week="2026-09-14", complete={"report": True, "compare": True})
    assert ei.value.code == "ORDER_WEEK_AMBIGUOUS"  # 订单 A 跨第 1、3 周，同样拒交
    assert loop.storage.list_tasks()[0].result is None


def test_single_usd_unit(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.data_dir.mkdir()
    df = pd.DataFrame({"销售额": [100, 200], "币种": ["USD", "USD"]})
    xlsx = cfg.data_dir / "s.xlsx"
    df.to_excel(xlsx, index=False)
    loop = Loop(cfg)
    result = loop.run("做周报", str(xlsx), amount_mode="A")
    total_fact = next(f for f in result["facts"] if f["id"] == "total_sales")
    assert total_fact["unit"] == "USD"


def test_bad_sales_error_no_raw_value():
    from workmate.tools import compute

    df = pd.DataFrame({"销售额": [100, "秘密敏感信息123"]})
    with pytest.raises(WorkmateError) as ei:
        compute.compute_all(df, {"sales": "销售额"}, "A")
    assert "秘密敏感信息123" not in ei.value.message


def test_empty_compare_week_does_not_block(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.data_dir.mkdir()
    df = pd.DataFrame({"日期": ["2026-09-01", "2026-09-15"], "销售额": [100, 200]})
    xlsx = cfg.data_dir / "s.xlsx"
    df.to_excel(xlsx, index=False)
    loop = Loop(cfg)
    result = loop.run("做周报", str(xlsx), amount_mode="A", report_week="2026-09-14", complete={"report": True, "compare": True})
    fact_ids = {f["id"] for f in result["facts"]}
    assert "mom_growth" not in fact_ids
    assert result["change_facts"] == []
    report = (Path(result["output_dir"]) / "report.md").read_text(encoding="utf-8")
    assert "对比周无记录" in report


def test_empty_report_week_errors(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.data_dir.mkdir()
    df = pd.DataFrame({"日期": ["2026-09-01"], "销售额": [100]})
    xlsx = cfg.data_dir / "s.xlsx"
    df.to_excel(xlsx, index=False)
    loop = Loop(cfg)
    with pytest.raises(WorkmateError) as ei:
        loop.run("做周报", str(xlsx), amount_mode="A", report_week="2026-09-14")
    assert ei.value.code == "REPORT_WEEK_EMPTY"


def test_inspect_respects_field_mapping(tmp_path):
    df = pd.DataFrame({"金额列": [1, 2, 3], "销售列": [10, 20, 30]})
    p = tmp_path / "x.xlsx"
    df.to_excel(p, index=False)
    r = inspect.inspect_file(p, field_mapping={"sales": "销售列"})
    assert r["mapping"]["sales"] == "销售列"
    assert r["quality"]["sales"]["valid"] == 3


def test_unit_unknown_without_currency(tmp_path, sample_df):
    cfg = _cfg(tmp_path)
    cfg.data_dir.mkdir()
    xlsx = cfg.data_dir / "s.xlsx"
    sample_df.to_excel(xlsx, index=False)
    loop = Loop(cfg)
    result = loop.run("做周报", str(xlsx), amount_mode="A")
    total = next(f for f in result["facts"] if f["id"] == "total_sales")
    assert total["unit"] == "单位待确认"


def test_summary_mode_fact_label(tmp_path, sample_df):
    cfg = _cfg(tmp_path)
    cfg.data_dir.mkdir()
    xlsx = cfg.data_dir / "s.xlsx"
    sample_df.to_excel(xlsx, index=False)
    loop = Loop(cfg)
    result = loop.run("做周报", str(xlsx), amount_mode="A")
    total = next(f for f in result["facts"] if f["id"] == "total_sales")
    assert total["label"] == "全表总销售额"
