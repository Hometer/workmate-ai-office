from pathlib import Path

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
    result = loop.run("把 sales.xlsx 做成销售周报", str(xlsx))

    out_dir = Path(result["output_dir"])
    report = out_dir / "report.md"
    assert report.exists()
    content = report.read_text(encoding="utf-8")
    assert "销售数据周报" in content
    assert "总销售额：920.00" in content
    assert (out_dir / "data_summary.xlsx").exists()
    charts = list((out_dir / "charts").glob("*.png"))
    assert len(charts) == 3

    # 原始文件未被改动
    assert xlsx.read_bytes() == before

    # 任务状态已持久化
    assert loop.storage.load_task(result["task_id"]) is not None


def test_error_returns_structured(tmp_path):
    cfg = _cfg(tmp_path)
    loop = Loop(cfg)
    try:
        loop.run("做个周报", str(tmp_path / "missing.xlsx"))
        assert False
    except Exception as e:  # noqa: BLE001
        d = e.to_dict()
        assert "error" in d and "code" in d["error"] and "message" in d["error"]
