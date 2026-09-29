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
    result = loop.run("做周报", str(xlsx), amount_mode="B", report_week="2026-09-14", complete={"report": True, "compare": True})
    fact_ids = {f["id"] for f in result["facts"]}
    assert "mom_growth" not in fact_ids  # 跨周订单，环比不可用


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
