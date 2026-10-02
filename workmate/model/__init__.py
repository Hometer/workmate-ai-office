"""模型层工厂。"""
from __future__ import annotations

from ..config import Config
from .base import ModelProvider
from .mock import MockProvider
from .ollama import OllamaProvider
from ..schemas import WorkmateError


def get_provider(config: Config) -> ModelProvider:
    if config.model_provider == "mock":
        return MockProvider()
    if config.model_provider != "ollama":
        raise WorkmateError("MODEL_CONFIG_INVALID", "模型配置无效，请在本地配置中选择 ollama 或开发演示模式。")
    return OllamaProvider(host=config.ollama_host, model=config.ollama_model)
