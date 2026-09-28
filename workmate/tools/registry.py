"""工具白名单（M1 五工具）。"""
from __future__ import annotations

# M1 骨架的工具白名单；safety_check / verify_metrics 在 M2 加入
TOOL_WHITELIST = [
    "search_files",
    "read_file",
    "compute_metrics",
    "plot_chart",
    "write_file",
]
