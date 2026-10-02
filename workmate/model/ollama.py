"""Ollama 本地模型提供商（HTTP API，数据不出本机）。"""
from __future__ import annotations

import requests

from ..schemas import WorkmateError
from .base import ModelProvider
from ..diagnostics import local_ollama_host


class OllamaProvider(ModelProvider):
    def __init__(self, host: str, model: str, timeout: int = 120):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        if not local_ollama_host(self.host):
            raise WorkmateError("MODEL_CONFIG_INVALID", "默认仅允许本机模型；请恢复本地配置后重试。")
        url = f"{self.host}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
        }
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout, allow_redirects=False)
            if 300 <= resp.status_code < 400:
                raise WorkmateError("MODEL_UNAVAILABLE", "本地模型发生重定向，已阻止发送；请检查本地服务。")
            resp.raise_for_status()
            data = resp.json()
            if data.get("done") is not True or not isinstance(data.get("message", {}).get("content"), str):
                raise WorkmateError("MODEL_ERROR", "本地模型未返回完整文本，请检查模型服务后重试。")
            return data["message"]["content"]
        except requests.exceptions.ConnectionError as e:
            raise WorkmateError(
                "MODEL_UNAVAILABLE",
                "无法连接本地 Ollama，请确认已启动 ollama serve；或把 WORKMATE_MODEL_PROVIDER 设为 mock。",
            ) from e
        except requests.exceptions.Timeout as e:
            raise WorkmateError("MODEL_TIMEOUT", "本地模型响应超时。") from e
        except WorkmateError:
            raise
        except Exception as e:  # noqa: BLE001
            raise WorkmateError("MODEL_ERROR", f"模型调用失败：{type(e).__name__}") from e
