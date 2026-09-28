"""FastAPI 应用：把后端引擎暴露为本地 Web API + 静态前端页面。"""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Config, load_config
from .loop import Loop
from .schemas import WorkmateError
from .tools import files as file_tools

STATIC_DIR = Path(__file__).resolve().parent / "static"


class TaskRequest(BaseModel):
    file: str
    instruction: str


def create_app(config: Config | None = None) -> FastAPI:
    config = config or load_config()
    config.ensure_dirs()
    loop = Loop(config)
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="workmate")

    app = FastAPI(title="WorkMate", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.exception_handler(WorkmateError)
    async def workmate_error_handler(request, exc: WorkmateError):
        status = 404 if exc.code == "NOT_FOUND" else 400
        return JSONResponse(status_code=status, content=exc.to_dict())

    def _run_task(task_id: str, instruction: str, file_path: str) -> None:
        try:
            loop.run(instruction, file_path, task_id=task_id)
        except WorkmateError:
            pass  # 任务状态已由 loop 持久化为 failed

    def _resolve_input(req_file: str) -> Path:
        p = Path(req_file).expanduser()
        if not p.is_absolute():
            p = config.data_dir / p
        if not p.exists():
            raise WorkmateError("FILE_NOT_FOUND", f"文件不存在：{req_file}")
        if not p.resolve().is_relative_to(config.data_dir.resolve()):
            raise WorkmateError("PERMISSION_DENIED", "只能读取 data 目录内的文件")
        return p

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/v1/data-files")
    def data_files():
        entries = file_tools.search_files("", config.data_dir)
        return {"files": [{"name": p.name, "size": p.stat().st_size} for p in entries]}

    @app.post("/api/v1/upload")
    async def upload(file: UploadFile = File(...)):
        name = Path(file.filename or "").name  # 安全文件名：只取 basename，防路径穿越
        if not name:
            raise WorkmateError("BAD_FILE", "文件名不能为空")
        if Path(name).suffix.lower() not in file_tools.ALLOWED_EXT:
            raise WorkmateError("UNSUPPORTED_FILE", "仅支持 xlsx/csv")
        data = await file.read()
        if len(data) > file_tools.MAX_FILE_MB * 1024 * 1024:
            raise WorkmateError("FILE_TOO_LARGE", f"文件超过 {file_tools.MAX_FILE_MB}MB 上限")
        (config.data_dir / name).write_bytes(data)
        return {"name": name, "size": len(data)}

    @app.post("/api/v1/tasks")
    def create_task(req: TaskRequest):
        if not (req.instruction and req.instruction.strip()):
            raise WorkmateError("BAD_INSTRUCTION", "请填写任务指令")
        p = _resolve_input(req.file)
        task_id = uuid.uuid4().hex[:12]
        executor.submit(_run_task, task_id, req.instruction.strip(), str(p))
        return {"task_id": task_id, "status": "running"}

    @app.get("/api/v1/tasks")
    def list_tasks():
        return {"tasks": [t.model_dump() for t in loop.storage.list_tasks()]}

    @app.get("/api/v1/tasks/{task_id}")
    def get_task(task_id: str):
        t = loop.storage.load_task(task_id)
        if t is None:
            raise WorkmateError("NOT_FOUND", "任务不存在")
        return t.model_dump()

    @app.get("/api/v1/tasks/{task_id}/report")
    def get_report(task_id: str):
        p = config.output_dir / task_id / "report.md"
        if not p.exists():
            raise WorkmateError("NOT_FOUND", "报告不存在")
        return {"report": p.read_text(encoding="utf-8")}

    @app.get("/api/v1/tasks/{task_id}/files/{name}")
    def get_file(task_id: str, name: str):
        base = (config.output_dir / task_id).resolve()
        target = (base / name).resolve()
        if not target.is_relative_to(base):
            raise WorkmateError("FORBIDDEN", "非法路径")
        if not target.exists():
            raise WorkmateError("NOT_FOUND", "文件不存在")
        return FileResponse(target)

    # 静态前端（挂载在最后，/api 优先匹配）
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    return app
