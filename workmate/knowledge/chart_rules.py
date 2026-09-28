"""图表规范（PRD §3.5）。"""

CHART_RULES = {
    "trend": {"title": "销售趋势", "kind": "line", "desc": "每日/每周销售额走势"},
    "top5": {"title": "Top5 商品", "kind": "bar", "desc": "前 5 商品销售额对比"},
    "channel": {"title": "渠道占比", "kind": "pie", "desc": "各渠道销售额占比"},
}
