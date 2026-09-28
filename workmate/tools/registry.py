"""工具白名单。"""
from __future__ import annotations

# M1 五工具 + M2 硬化两工具（verify_metrics / safety_check）
TOOL_WHITELIST = [
    "search_files",
    "read_file",
    "compute_metrics",
    "plot_chart",
    "write_file",
    "verify_metrics",
    "safety_check",
]
