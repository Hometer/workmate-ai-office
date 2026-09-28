"""模型层工厂。"""
from __future__ import annotations

from ..config import Config
from .base import ModelProvider
from .mock import MockProvider
from .ollama import OllamaProvider


def get_provider(config: Config) -> ModelProvider:
    if config.model_provider == "mock":
        return MockProvider()
    return OllamaProvider(host=config.ollama_host, model=config.ollama_model)
