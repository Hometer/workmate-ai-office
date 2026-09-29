from pathlib import Path

import pandas as pd

from workmate.config import Config
from workmate.loop import Loop
from workmate.schemas import WorkmateError
from workmate.tools import files


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


def test_read_outside_data_dir_denied(tmp_path, sample_df):
    cfg = _cfg(tmp_path)
    cfg.data_dir.mkdir()
    outside = tmp_path / "outside.xlsx"
    sample_df.to_excel(outside, index=False)
    loop = Loop(cfg)
    try:
        loop.run("做个周报", str(outside), amount_mode="A")
        assert False
    except WorkmateError as e:
        assert e.code == "PERMISSION_DENIED"


def test_write_existing_requires_overwrite(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    target = out / "report.md"
    target.write_text("old", encoding="utf-8")
    try:
        files.write_file(target, "new", out)
        assert False
    except WorkmateError as e:
        assert e.code == "FILE_EXISTS"
    files.write_file(target, "new", out, overwrite=True)
    assert target.read_text(encoding="utf-8") == "new"


def test_write_original_never_overwritten(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    original = tmp_path / "data.xlsx"
    original.write_bytes(b"raw")
    try:
        files.write_file(original, "x", out, input_file=original, overwrite=True)
        assert False
    except WorkmateError as e:
        assert e.code == "WRITE_FORBIDDEN"
