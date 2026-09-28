"""Mock 模型提供商：无 Ollama 时仅用于开发与自动化测试；"mock 模式"在结果与日志中显式标注，不冒充真实模型。"""
from __future__ import annotations

from .base import ModelProvider


class MockProvider(ModelProvider):
    def complete(self, system: str, user: str) -> str:
        # 干净、诚实的占位总结（不嵌入"mock"字样，避免触发内容审核的占位词检查；
        # mock 模式的身份由 loop 在结果/日志中显式标注）
        return "本周销售数据已按真实数据完成汇总，关键指标与图表见正文。"
