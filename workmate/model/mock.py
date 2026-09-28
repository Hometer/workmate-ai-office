"""Mock 模型提供商：无 Ollama 时仅用于开发与自动化测试，不冒充真实模型。"""
from __future__ import annotations

from .base import ModelProvider


class MockProvider(ModelProvider):
    def complete(self, system: str, user: str) -> str:
        return (
            "本周销售整体平稳，关键指标已按真实数据汇总，详见下方数字与图表。"
            "（mock 模式：本段为开发期占位总结，安装 Ollama 后自动切换为真实生成。）"
        )
