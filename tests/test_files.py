from pathlib import Path

import pandas as pd

from workmate.schemas import WorkmateError
from workmate.tools import files


def test_read_table_xlsx(sample_xlsx):
    df = files.read_table(sample_xlsx)
    assert list(df.columns) == ["订单号", "日期", "商品", "渠道", "销售额"]
    assert len(df) == 6


def test_read_table_csv(tmp_path):
    p = tmp_path / "s.csv"
    pd.DataFrame({"销售额": [1, 2]}).to_csv(p, index=False)
    df = files.read_table(p)
    assert df["销售额"].sum() == 3


def test_read_table_rejects_unsupported(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("hello")
    try:
        files.read_table(p)
        assert False
    except WorkmateError as e:
        assert e.code == "UNSUPPORTED_FILE"


def test_read_table_rejects_xls(tmp_path):
    p = tmp_path / "old.xls"
    p.write_bytes(b"fake")
    try:
        files.read_table(p)
        assert False
    except WorkmateError as e:
        assert e.code == "UNSUPPORTED_FILE"


def test_read_table_rejects_missing(tmp_path):
    try:
        files.read_table(tmp_path / "nope.xlsx")
        assert False
    except WorkmateError as e:
        assert e.code == "FILE_NOT_FOUND"


def test_write_file_refuses_outside_output(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    try:
        files.write_file(tmp_path / "evil.md", "x", out)
        assert False
    except WorkmateError as e:
        assert e.code == "WRITE_FORBIDDEN"


def test_write_file_refuses_overwrite_original(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    original = tmp_path / "data.xlsx"
    original.write_bytes(b"raw")
    try:
        files.write_file(original, "x", out, input_file=original)
        assert False
    except WorkmateError as e:
        assert e.code == "WRITE_FORBIDDEN"


def test_search_files(tmp_path):
    (tmp_path / "sales.xlsx").write_bytes(b"a")
    (tmp_path / "report.csv").write_bytes(b"b")
    (tmp_path / "note.txt").write_text("c")
    hits = files.search_files("sales", tmp_path)
    assert [p.name for p in hits] == ["sales.xlsx"]
