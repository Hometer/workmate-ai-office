"""Mock 模型提供商：无 Ollama 时仅用于开发与自动化测试；"mock 模式"在结果与日志中显式标注，不冒充真实模型。"""
from __future__ import annotations

from .base import ModelProvider
import json


class MockProvider(ModelProvider):
    def complete(self, system: str, user: str) -> str:
        try:
            facts = json.loads(user)
            selected = [{"fact_id": f["id"], "value": f["value"]} for f in facts if f["id"] in {"total_sales", "order_count"}][:2]
        except (ValueError, TypeError, KeyError):
            selected = []
        return json.dumps({"statements": selected}, ensure_ascii=False)
