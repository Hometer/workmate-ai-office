from pathlib import Path

import pandas as pd

from workmate.config import Config
from workmate.loop import Loop


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


def test_end_to_end(tmp_path, sample_df):
    cfg = _cfg(tmp_path)
    cfg.data_dir.mkdir()
    xlsx = cfg.data_dir / "sales.xlsx"
    sample_df.to_excel(xlsx, index=False)
    before = xlsx.read_bytes()

    loop = Loop(cfg)
    result = loop.run("把 sales.xlsx 做成销售周报", str(xlsx), amount_mode="A")

    out_dir = Path(result["output_dir"])
    report = out_dir / "report.md"
    assert report.exists()
    content = report.read_text(encoding="utf-8")
    assert "销售数据汇总" in content
    assert "总销售额：920.00 元" in content
    assert "明细行数：6" in content
    assert "订单量（订单号去重）：6" in content
    assert "环比增长率" not in content  # 未选报告周 → 汇总模式，无环比
    assert (out_dir / "data_summary.xlsx").exists()
    summary = pd.read_excel(out_dir / "data_summary.xlsx", sheet_name="关键指标")
    assert summary.loc[summary["指标"] == "明细行数", "数值"].iloc[0] == 6
    charts = list((out_dir / "charts").glob("*.png"))
    assert len(charts) == 3

    # 原始文件未被改动
    assert xlsx.read_bytes() == before

    # 任务状态已持久化，且包含 M2 钩子步骤
    saved = loop.storage.load_task(result["task_id"])
    assert saved is not None
    step_names = [s.name for s in saved.steps]
    assert "verify_metrics" in step_names
    assert "safety_check" in step_names

    # 人读日志已生成
    assert loop.storage.app_log_path.exists()


def test_error_returns_structured(tmp_path):
    cfg = _cfg(tmp_path)
    loop = Loop(cfg)
    try:
        loop.run("做个周报", str(tmp_path / "missing.xlsx"), amount_mode="A")
        assert False
    except Exception as e:  # noqa: BLE001
        d = e.to_dict()
        assert "error" in d and "code" in d["error"] and "message" in d["error"]
    saved = loop.storage.list_tasks()[0]
    assert saved.status == "failed"
    assert saved.error == d["error"]


def test_unexpected_failure_is_persisted_without_input_in_log(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    loop = Loop(cfg)
    monkeypatch.setattr(loop, "_execute", lambda *_: 1 / 0)
    instruction = "私人指令内容"
    try:
        loop.run(instruction, amount_mode="A")
        assert False
    except Exception as e:  # noqa: BLE001
        assert e.to_dict()["error"]["code"] == "INTERNAL_ERROR"
    saved = loop.storage.list_tasks()[0]
    assert saved.status == "failed"
    assert saved.error["code"] == "INTERNAL_ERROR"
    assert instruction not in loop.storage.app_log_path.read_text(encoding="utf-8")
