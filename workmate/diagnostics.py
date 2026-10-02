"""本地启动诊断：不读业务内容、不外发、不自动切换模型。"""
from __future__ import annotations

import tempfile
from urllib.parse import urlsplit

import requests

from .config import Config


def local_ollama_host(host: str) -> bool:
    try:
        url = urlsplit(host)
        return url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"} and not url.username and not url.password and not url.query and not url.fragment and url.path in {"", "/"}
    except ValueError:
        return False


def _directory(path, code, label) -> dict:
    try:
        if not path.is_dir():
            raise OSError("missing directory")
        # 目录枚举验证可读，临时文件验证可写，不读取或改写业务文件。
        next(path.iterdir(), None)
        with tempfile.TemporaryFile(prefix=".workmate-probe-", dir=path) as probe:
            probe.write(b"ok")
            probe.flush()
        return {"code": code, "status": "ready", "message": f"{label}可读取和写入", "steps": []}
    except OSError:
        return {"code": code, "status": "failed", "message": f"{label}不可用", "steps": [f"打开本地配置 .env，核对{'WORKMATE_DATA_DIR' if code == 'data_directory' else 'WORKMATE_OUTPUT_DIR'} 指向你有读写权限的文件夹。", "重启 WorkMate 后点“重新检查环境”，看到目录可用算正确；不要删除原表或旧成果。"]}


def diagnose(config: Config) -> dict:
    checks = [_directory(config.data_dir, "data_directory", "数据目录"), _directory(config.output_dir, "output_directory", "成果目录")]
    if config.model_provider == "mock":
        model = {"code": "model", "status": "pending", "message": "当前为演示模式，未调用真实模型", "steps": ["要验收真实模型，请在本地 .env 把 WORKMATE_MODEL_PROVIDER 设置为 ollama，并启动本地 Ollama 后重启 WorkMate。", "点“重新检查环境”，看到指定模型可用才开始真实验收。"]}
    elif config.model_provider != "ollama" or not local_ollama_host(config.ollama_host):
        model = {"code": "model", "status": "failed", "message": "本地模型配置不符合本机处理约定", "steps": ["在 .env 中使用 WORKMATE_MODEL_PROVIDER=ollama、WORKMATE_OLLAMA_HOST=http://localhost:11434，重启后重新检查。", "切换云端需先脱敏并单独授权，系统不会自动切换。"]}
    else:
        try:
            response = requests.get(f"{config.ollama_host.rstrip('/')}/api/tags", timeout=2, allow_redirects=False)
            if response.status_code != 200:
                raise ValueError("invalid response")
            names = {x.get("name") or x.get("model") for x in response.json()["models"]}
            expected = config.ollama_model if ":" in config.ollama_model else config.ollama_model + ":latest"
            if expected not in names:
                model = {"code": "model", "status": "failed", "message": "本地服务可连接，指定模型尚未下载", "steps": ["打开终端，按 README 的本地模型安装步骤下载已约定模型。", "下载完成后点“重新检查环境”，看到指定模型可用算正确。"]}
            else:
                model = {"code": "model", "status": "ready", "message": "真实本地模型已就绪；业务样表质量仍需验收", "steps": []}
        except Exception:
            model = {"code": "model", "status": "failed", "message": "无法连接本地模型，或服务返回无效状态", "steps": ["打开 Ollama 应用并保持运行；如未安装，按 README 的官方安装步骤操作。", "点“重新检查环境”，看到指定模型可用算正确；已有任务与下载仍可查看。"]}
    checks.append(model)
    return {"status": "ready" if all(x["status"] == "ready" for x in checks) else "needs_attention", "model_mode": config.model_provider, "model_name": config.ollama_model if config.model_provider == "ollama" else None, "checks": checks}
