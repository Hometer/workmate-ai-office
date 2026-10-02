"""s02 工具系统：文件读写（M1 五工具中的三个 + 汇总表导出）。"""
from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
from io import BytesIO
import hashlib
import os

import pandas as pd

from ..schemas import WorkmateError

MAX_FILE_MB = 20
ALLOWED_EXT = {".xlsx", ".csv"}


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


@dataclass(frozen=True)
class TableSnapshot:
    content: bytes
    suffix: str
    fingerprint: str

    def __post_init__(self):
        if self.fingerprint != hashlib.sha256(self.content).hexdigest() or self.suffix not in ALLOWED_EXT:
            raise WorkmateError("CONFIRMATION_INVALID", "数据版本无效，请重新检查原表。")

    def table(self) -> pd.DataFrame:
        try:
            if self.suffix == ".csv":
                if b"\x00" in self.content:
                    raise ValueError("binary CSV")
                return pd.read_csv(BytesIO(self.content))
            return pd.read_excel(BytesIO(self.content))
        except Exception as exc:
            raise WorkmateError("FILE_PARSE_FAILED", "文件内容不是可读取的表格，请检查格式后重试。") from exc


def read_snapshot(path) -> TableSnapshot:
    """读 xlsx/csv，校验格式、真实存在与大小；解析失败显式报错。"""
    p = Path(path)
    if p.suffix.lower() not in ALLOWED_EXT:
        raise WorkmateError("UNSUPPORTED_FILE", f"仅支持 xlsx/csv，收到 {p.suffix}")
    if not p.exists():
        raise WorkmateError("FILE_NOT_FOUND", f"文件不存在：{p}")
    if p.stat().st_size > MAX_FILE_MB * 1024 * 1024:
        raise WorkmateError("FILE_TOO_LARGE", f"文件超过 {MAX_FILE_MB}MB 上限")
    try:
        with p.open("rb") as source:
            before = os.fstat(source.fileno())
            content = source.read(MAX_FILE_MB * 1024 * 1024 + 1)
            after = os.fstat(source.fileno())
        if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            raise WorkmateError("SOURCE_CHANGED", "数据表在读取时发生变化，请等待保存完成后重新检查。")
    except OSError as exc:
        raise WorkmateError("FILE_READ_FAILED", "无法读取数据表，请检查文件及读取权限。") from exc
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        raise WorkmateError("FILE_TOO_LARGE", f"文件超过 {MAX_FILE_MB}MB 上限")
    snapshot = TableSnapshot(content, p.suffix.lower(), hashlib.sha256(content).hexdigest())
    snapshot.table()  # 校验真实内容，保证凭据不绑定无法解析的文件
    return snapshot


def read_table(path) -> pd.DataFrame:
    return read_snapshot(path).table()


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


def write_metrics_xlsx(metrics: dict, target: Path, output_dir: Path, *, context: dict | None = None) -> None:
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
    ctx = context or {}
    unit = ctx.get("unit", "单位待确认")
    scope = ctx.get("scope", "全表")
    for row in key_rows:
        row["单位"] = unit if row["指标"] in {"总销售额", "客单价"} else "行" if row["指标"] == "明细行数" else "单" if row["指标"] == "订单量（订单号去重）" else "比例（×100 为 %）"
        row["统计范围"] = scope
    if not top5_df.empty:
        top5_df["单位"] = unit
        top5_df["统计范围"] = scope
    if not channel_df.empty:
        channel_df["占比单位"] = "比例（×100 为 %）"
        channel_df["金额单位"] = unit
        channel_df["统计范围"] = scope
    validation = ctx.get("summary_validation") or {}
    identity = "演示模式，未调用真实模型" if validation.get("provider") == "mock" else "确定性降级摘要" if validation.get("status") == "fallback" else "真实模型摘要已通过结构与事实校验，业务质量待人工验收"
    meta = [
        {"项目": "统计范围", "说明": scope}, {"项目": "金额单位", "说明": unit},
        {"项目": "单位来源", "说明": {"field": "字段识别", "user": "人工声明", "pending": "待确认"}.get(ctx.get("unit_source"), "待确认")},
        {"项目": "金额口径", "说明": ctx.get("amount_mode", "待确认")},
        {"项目": "数字核对", "说明": "本次统计范围已核对，不代表业务数据完整"},
        {"项目": "报告周", "说明": ctx.get("report_week") or "不适用（全表）"},
        {"项目": "对比周", "说明": ctx.get("compare_week") or "不适用（全表）"},
        {"项目": "人工完整性", "说明": "不适用（全表）" if ctx.get("summary_mode") else f"报告周{'已确认' if (ctx.get('completeness') or {}).get('report') else '未确认'}，对比周{'已确认' if (ctx.get('completeness') or {}).get('compare') else '未确认'}"},
        {"项目": "总结身份", "说明": identity},
        {"项目": "限制", "说明": "；".join(ctx.get("warnings") or []) or "无额外计算限制；业务完整性由用户确认"},
    ]
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        pd.DataFrame(key_rows).to_excel(writer, sheet_name="关键指标", index=False)
        if not top5_df.empty:
            top5_df.to_excel(writer, sheet_name="Top5", index=False)
        if not channel_df.empty:
            channel_df.to_excel(writer, sheet_name="渠道占比", index=False)
        pd.DataFrame(meta).to_excel(writer, sheet_name="口径与限制", index=False)
        for sheet in writer.book.worksheets:
            for cells in sheet:
                for cell in cells:
                    if cell.data_type == "f":
                        cell.data_type = "s"  # 用户维度/单位文本不作为公式执行
