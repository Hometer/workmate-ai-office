"""指标算法定义（PRD §3.4）。M1 只维护定义元数据，计算实现在 tools/compute.py。"""

METRIC_DEFINITIONS = {
    "total_sales": {"display": "总销售额", "deps": ["sales"], "desc": "sum(销售额列)"},
    "order_count": {"display": "订单量", "deps": ["order"], "desc": "count(订单行)"},
    "avg_order_value": {"display": "客单价", "deps": ["sales", "order"], "desc": "总销售额 ÷ 订单量"},
    "mom_growth": {"display": "环比增长率", "deps": ["sales", "date"], "desc": "(本周 − 上周) ÷ 上周"},
    "top5": {"display": "Top5 商品", "deps": ["sales", "product"], "desc": "按销售额降序取前 5"},
    "channel_share": {"display": "渠道占比", "deps": ["sales", "channel"], "desc": "各渠道销售额 ÷ 总销售额"},
}
