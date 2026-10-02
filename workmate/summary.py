"""模型只能选择已核对事实；所有业务正文由可信事实确定性渲染。"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SYSTEM = '''你是 WorkMate 销售报告助手。从给定的已核对事实中选择最重要的 1 到 3 条。
只输出 JSON：{"statements":[{"fact_id":"total_sales","value":600}]}。
fact_id 必须来自输入；value 原样复制对应事实的 value，百分比使用输入显示的百分数。
禁止额外字段、正文、原因、预测、建议或不可用事实。禁止将订单量写成销售额。
可选 direction 仅限 mom_growth：正值 increase，负值 decrease，零 flat。
不确定方向时省略 direction。正确例：{"statements":[{"fact_id":"order_count","value":3}]}。
错误例：{"statements":[{"fact_id":"order_count","value":9,"text":"因促销上涨"}]}。'''


class Statement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    fact_id: str
    value: Any
    direction: Literal["increase", "decrease", "flat"] | None = None


class SummarySelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    statements: list[Statement] = Field(min_length=1, max_length=3)


def _same(actual, expected) -> bool:
    if isinstance(actual, bool) or actual is None:
        return actual is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(actual, (int, float)) and actual == expected and math.isfinite(actual)
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(_same(a, b) for a, b in zip(actual, expected))
    if isinstance(expected, dict):
        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(_same(actual[k], expected[k]) for k in expected)
    return type(actual) is type(expected) and actual == expected


def _display(value) -> str:
    if isinstance(value, list):
        return "、".join(str(v) for v in value)
    if isinstance(value, dict):
        return "、".join(f"{k} {v}%" for k, v in value.items())
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def model_facts(facts: list[dict]) -> list[dict]:
    safe = []
    for fact in facts:
        item = dict(fact)
        item["source_col"] = item["id"]
        if isinstance(item["value"], list):
            item["value"] = [f"商品{i + 1}" for i in range(len(item["value"]))]
        elif isinstance(item["value"], dict):
            item["value"] = {f"渠道{i + 1}": v for i, v in enumerate(item["value"].values())}
        safe.append(item)
    return safe


def validate_and_render(raw: str, facts: list[dict], *, render_facts: list[dict] | None = None) -> str:
    if not isinstance(raw, str) or len(raw) > 32768:
        raise ValueError("invalid output type")
    text = raw.strip()
    fence = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence:
        text = fence.group(1)
    def reject_duplicates(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("duplicate key")
            result[k] = v
        return result
    try:
        parsed = json.loads(text, object_pairs_hook=reject_duplicates, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    except RecursionError as exc:
        raise ValueError("output nesting too deep") from exc
    selection = SummarySelection.model_validate(parsed)
    by_id = {f["id"]: f for f in facts if f.get("verified")}
    render_by_id = {f["id"]: f for f in (render_facts if render_facts is not None else facts) if f.get("verified")}
    seen = set()
    sentences = []
    for item in selection.statements:
        fact = by_id.get(item.fact_id)
        if fact is None or item.fact_id in seen or not _same(item.value, fact["value"]):
            raise ValueError("invalid fact or value")
        seen.add(item.fact_id)
        direction = ""
        if item.direction is not None:
            if item.fact_id != "mom_growth" or not isinstance(fact["value"], (int, float)):
                raise ValueError("unsupported direction")
            expected = "increase" if fact["value"] > 0 else "decrease" if fact["value"] < 0 else "flat"
            if item.direction != expected:
                raise ValueError("invalid direction")
            direction = {"increase": "（增长）", "decrease": "（下降）", "flat": "（持平）"}[expected]
        fact = render_by_id[item.fact_id]
        unit = "" if isinstance(fact["value"], (list, dict)) else f" {fact.get('unit') or ''}".rstrip()
        sentences.append(f"{fact['label']} {_display(fact['value'])}{unit}{direction} [{item.fact_id}]")
    rendered = "；".join(sentences) + "。"
    if len(rendered) > 200:
        raise ValueError("summary too long")
    return rendered
