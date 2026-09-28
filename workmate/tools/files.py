"""s02 工具系统：文件读写（M1 五工具中的三个 + 汇总表导出）。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..schemas import WorkmateError

MAX_FILE_MB = 20
ALLOWED_EXT = {".xlsx", ".xls", ".csv"}


def ensure_within_output_dir(target: Path, output_dir: Path) -> None:
    """红线：写文件只能落在成品目录内。"""
    if not Path(target).resolve().is_relative_to(Path(output_dir).resolve()):
        raise WorkmateError("WRITE_FORBIDDEN", "只能写入成品目录，不允许写其他位置。")


def search_files(keyword: str, data_dir: Path) -> list[Path]:
    data_dir = Path(data_dir)
    if not data_dir.exists():
        return []
    kw = (keyword or "").lower()
    return [
        p
        for p in sorted(data_dir.iterdir())
        if p.is_file() and p.suffix.lower() in ALLOWED_EXT and kw in p.name.lower()
    ]


def read_table(path) -> pd.DataFrame:
    """读 xlsx/csv，校验格式、真实存在与大小；解析失败显式报错。"""
    p = Path(path)
    if p.suffix.lower() not in ALLOWED_EXT:
        raise WorkmateError("UNSUPPORTED_FILE", f"仅支持 xlsx/csv，收到 {p.suffix}")
    if not p.exists():
        raise WorkmateError("FILE_NOT_FOUND", f"文件不存在：{p}")
    if p.stat().st_size > MAX_FILE_MB * 1024 * 1024:
        raise WorkmateError("FILE_TOO_LARGE", f"文件超过 {MAX_FILE_MB}MB 上限")
    try:
        if p.suffix.lower() == ".csv":
            return pd.read_csv(p)
        return pd.read_excel(p)
    except Exception as e:  # noqa: BLE001
        raise WorkmateError("FILE_PARSE_FAILED", f"文件打不开或表结构不清：{type(e).__name__}") from e


def describe_schema(df: pd.DataFrame) -> dict:
    return {
        "shape": list(df.shape),
        "columns": [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns],
        "preview": df.head(5).to_dict(orient="records"),
    }


def write_file(target: Path, content: str, output_dir: Path, input_file: Path | None = None, overwrite: bool = False) -> None:
    """写文本文件到成品目录；红线：不写目录外、不覆盖原始数据文件、命中已有文件需确认。"""
    ensure_within_output_dir(target, output_dir)
    if input_file is not None and Path(target).resolve() == Path(input_file).resolve():
        raise WorkmateError("WRITE_FORBIDDEN", "原始数据文件只读，禁止覆盖。")
    if Path(target).exists() and not overwrite:
        raise WorkmateError("FILE_EXISTS", f"目标已存在：{Path(target).name}。如需覆盖请加 --force。")
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    Path(target).write_text(content, encoding="utf-8")


def write_metrics_xlsx(metrics: dict, target: Path, output_dir: Path) -> None:
    """把计算结果导出为 data_summary.xlsx（关键指标 + Top5 + 渠道）。"""
    ensure_within_output_dir(target, output_dir)
    key_rows = [
        {"指标": "总销售额", "数值": metrics.get("total_sales")},
        {"指标": "明细行数", "数值": metrics.get("line_count")},
        {"指标": "订单量（订单号去重）", "数值": metrics.get("order_count") if metrics.get("order_count") is not None else "待确认"},
        {"指标": "客单价", "数值": metrics.get("avg_order_value") if metrics.get("avg_order_value") is not None else "待确认"},
        {"指标": "环比增长率", "数值": metrics.get("mom_growth")},
    ]
    top5_df = pd.DataFrame(metrics.get("top5") or [])
    channel_df = pd.DataFrame(metrics.get("channel_share") or [])
    with pd.ExcelWriter(target) as writer:
        pd.DataFrame(key_rows).to_excel(writer, sheet_name="关键指标", index=False)
        if not top5_df.empty:
            top5_df.to_excel(writer, sheet_name="Top5", index=False)
        if not channel_df.empty:
            channel_df.to_excel(writer, sheet_name="渠道占比", index=False)
