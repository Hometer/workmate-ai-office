"""s05 任务规划。M1 固定标准销售周报管线，不引入模型自由规划。"""
from __future__ import annotations

PLAN_STEPS = [
    "search_files",
    "read_file",
    "infer_columns",
    "compute_metrics",
    "verify_metrics",
    "plot_chart",
    "write_summary",
    "safety_check",
    "write_files",
]


def build_plan(instruction: str) -> list[str]:
    """M1 只支持标准周报，返回固定步骤。"""
    return list(PLAN_STEPS)
