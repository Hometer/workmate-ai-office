"""配置加载：读 .env（不含任何秘密，本地模型免费）。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def _resolve(path_str: str) -> Path:
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


class Config:
    def __init__(self, data: dict):
        self.data_dir: Path = data["data_dir"]
        self.output_dir: Path = data["output_dir"]
        self.model_provider: str = data["model_provider"]
        self.ollama_host: str = data["ollama_host"]
        self.ollama_model: str = data["ollama_model"]

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    load_dotenv()
    return Config(
        {
            "data_dir": _resolve(os.getenv("WORKMATE_DATA_DIR", "./data")),
            "output_dir": _resolve(os.getenv("WORKMATE_OUTPUT_DIR", "./outputs")),
            "model_provider": os.getenv("WORKMATE_MODEL_PROVIDER", "ollama"),
            "ollama_host": os.getenv("WORKMATE_OLLAMA_HOST", "http://localhost:11434"),
            "ollama_model": os.getenv("WORKMATE_OLLAMA_MODEL", "qwen2.5:7b"),
        }
    )
