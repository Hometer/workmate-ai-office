"""Public, bounded interview demo. The normal local app remains unchanged."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi.responses import JSONResponse

from .config import Config
from .loop import Loop
from .schemas import WorkmateError

COOKIE = "workmate_demo"
SAMPLE_NAME = "合成销售样例.csv"
SAMPLE = ("\ufeff日期,订单号,销售额,商品,渠道,币种\n"
          "2026-09-21,DEMO01,100,文具,线上,USD\n"
          "2026-09-22,DEMO02,200,纸张,门店,USD\n"
          "2026-09-28,DEMO03,125.50,笔,线上,USD\n"
          "2026-09-29,DEMO04,74.50,纸张,门店,USD\n"
          "2026-09-30,DEMO05,400,本册,线上,USD\n").encode("utf-8")
SAMPLE_HASH = hashlib.sha256(SAMPLE).digest()


@dataclass
class DemoContext:
    config: Config
    loop: Loop
    lock: threading.Lock


class DemoManager:
    def __init__(self, root: Path, secret: str, *, secure=True, ttl=7200,
                 max_sessions=24, max_tasks=5, max_jobs=2):
        if len(secret) < 32:
            raise ValueError("WORKMATE_DEMO_SECRET must contain at least 32 characters")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.secret = secret.encode()
        self.secure = secure
        self.ttl = ttl
        self.max_sessions = max_sessions
        self.max_tasks = max_tasks
        self.contexts: dict[str, DemoContext] = {}
        self.lock = threading.RLock()
        self.jobs = threading.BoundedSemaphore(max_jobs)
        self.active: dict[str, int] = {}

    def _sign(self, value: str) -> str:
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def _parse(self, token: str | None):
        if not token or len(token) > 160:
            return None
        match = re.fullmatch(r"([0-9a-f]{32})\.([0-9]{10})\.([0-9a-f]{64})", token)
        if not match:
            return None
        sid, expires, signature = match.groups()
        if int(expires) <= time.time() or not hmac.compare_digest(signature, self._sign(f"{sid}.{expires}")):
            return None
        return sid, int(expires)

    def session(self, token: str | None) -> tuple[str, str, int]:
        with self.lock:
            self._cleanup()
            parsed = self._parse(token)
            if parsed and (self.root / parsed[0] / "session.json").is_file():
                return parsed[0], token, parsed[1]
            count = sum(p.is_dir() and re.fullmatch(r"[0-9a-f]{32}", p.name) is not None for p in self.root.iterdir())
            if count >= self.max_sessions:
                raise WorkmateError("DEMO_BUSY", "演示工作区暂时已满，请稍后再试。")
            sid = secrets.token_hex(16)
            expires = int(time.time()) + self.ttl
            directory = self.root / sid
            directory.mkdir()
            (directory / "session.json").write_text(json.dumps({"expires": expires}))
            value = f"{sid}.{expires}"
            return sid, f"{value}.{self._sign(value)}", expires

    def _cleanup(self):
        for directory in self.root.iterdir():
            if not directory.is_dir() or not re.fullmatch(r"[0-9a-f]{32}", directory.name):
                continue
            try:
                expired = json.loads((directory / "session.json").read_text())["expires"] <= time.time()
            except (OSError, ValueError, KeyError, TypeError):
                expired = False
            if expired and not self.active.get(directory.name):
                self.contexts.pop(directory.name, None)
                shutil.rmtree(directory)

    def context(self, sid: str) -> DemoContext:
        with self.lock:
            if sid not in self.contexts:
                cfg = Config({"data_dir": self.root / sid / "data", "output_dir": self.root / sid / "outputs",
                              "model_provider": "mock", "ollama_host": "http://localhost:11434", "ollama_model": ""})
                cfg.ensure_dirs()
                sample = cfg.data_dir / SAMPLE_NAME
                if not sample.exists():
                    sample.write_bytes(SAMPLE)
                loop = Loop(cfg)
                loop.storage.recover_interrupted()
                self.contexts[sid] = DemoContext(cfg, loop, threading.Lock())
            return self.contexts[sid]

    def reserve_job(self, sid: str):
        with self.lock:
            if self.active.get(sid):
                raise WorkmateError("DEMO_BUSY", "已有周报正在生成，请等待完成后再试。")
            if not self.jobs.acquire(blocking=False):
                raise WorkmateError("DEMO_BUSY", "演示正在处理其他周报，请稍后再试。")
            self.active[sid] = 1

    def release_job(self, sid: str):
        with self.lock:
            self.active.pop(sid, None)
            self.jobs.release()


class DemoBoundary:
    """Sign sessions, reject cross-site mutations and bound body size before parsing."""
    def __init__(self, app, manager: DemoManager):
        self.app, self.manager = app, manager

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return
        from http.cookies import SimpleCookie
        from urllib.parse import urlsplit
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope["headers"]}
        if scope["method"] not in {"GET", "HEAD", "POST"}:
            await self._error(scope, receive, send, 405, "METHOD_NOT_ALLOWED", "演示不支持此操作。")
            return
        if scope["method"] == "POST":
            origin = headers.get("origin")
            if headers.get("sec-fetch-site") == "cross-site" or (origin and urlsplit(origin).netloc != headers.get("host")):
                await self._error(scope, receive, send, 403, "FORBIDDEN", "请在演示页面内执行操作。")
                return
            chunks, size = [], 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > 64 * 1024:
                    await self._error(scope, receive, send, 413, "DEMO_BODY_TOO_LARGE", "演示请求过大，请使用内置合成样表。")
                    return
                chunks.append(chunk)
                if not message.get("more_body"):
                    break
            body = b"".join(chunks)
            sent = False
            original_receive = receive

            async def buffered_receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await original_receive()

            receive = buffered_receive
        cookie = None
        if scope["path"] != "/healthz":
            try:
                jar = SimpleCookie()
                jar.load(headers.get("cookie", ""))
                token = jar[COOKIE].value if COOKIE in jar else None
                sid, token, expires = self.manager.session(token)
                scope.setdefault("state", {})["demo_session"] = sid
                jar = SimpleCookie()
                jar[COOKIE] = token
                jar[COOKIE]["path"] = "/"
                jar[COOKIE]["httponly"] = True
                jar[COOKIE]["samesite"] = "Lax"
                jar[COOKIE]["max-age"] = max(1, expires - int(time.time()))
                if self.manager.secure:
                    jar[COOKIE]["secure"] = True
                cookie = jar[COOKIE].OutputString().encode("latin1")
            except WorkmateError as exc:
                response = JSONResponse(exc.to_dict(), status_code=429)
                await response(scope, receive, send)
                return

        async def protected_send(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend([(b"x-content-type-options", b"nosniff"),
                                         (b"referrer-policy", b"same-origin"),
                                         (b"x-frame-options", b"DENY")])
                if cookie:
                    response_headers.append((b"set-cookie", cookie))
                if scope["path"].startswith("/api/"):
                    response_headers.append((b"cache-control", b"no-store"))
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, protected_send)

    @staticmethod
    async def _error(scope, receive, send, status, code, message):
        await JSONResponse({"error": {"code": code, "message": message}}, status_code=status)(scope, receive, send)


def create_demo_app():
    from .api import create_app
    manager = DemoManager(Path(os.getenv("WORKMATE_DEMO_DIR", "./data/render-demo")),
                          os.environ.get("WORKMATE_DEMO_SECRET", ""),
                          secure=os.getenv("WORKMATE_DEMO_SECURE_COOKIE", "1") != "0")
    return create_app(demo=manager)
