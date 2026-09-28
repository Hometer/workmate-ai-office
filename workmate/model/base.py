"""模型层抽象：本地优先，预留云端切换（M1 只实现 Ollama 与 mock）。"""
from __future__ import annotations

from abc import ABC, abstractmethod


class ModelProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """返回模型生成的文本。失败应抛 WorkmateError（统一错误结构）。"""
