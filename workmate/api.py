"""FastAPI 应用：把后端引擎暴露为本地 Web API + 静态前端页面。"""
from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Literal

from . import inspect
from .config import Config, load_config
from .loop import Loop
from .schemas import WorkmateError
from .schemas import Task, now_iso
from .diagnostics import diagnose
from .tools import compute
from .tools import files as file_tools

STATIC_DIR = Path(__file__).resolve().parent / "static"


class LocalStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


class InspectRequest(BaseModel):
    file: str
    field_mapping: dict | None = None


class TaskRequest(BaseModel):
    file: str
    instruction: str
    field_mapping: dict | None = None
    amount_mode: Literal["A", "B"]
    report_week: str | None = None
    compare_week: str | None = None
    complete: dict | None = None
    unit: str | None = None
    confirmation_id: str | None = None


def create_app(config: Config | None = None) -> FastAPI:
    config = config or load_config()
    config.ensure_dirs()
    loop = Loop(config)
    loop.storage.recover_interrupted()
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="workmate")

    app = FastAPI(title="WorkMate", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.exception_handler(WorkmateError)
    async def workmate_error_handler(request, exc: WorkmateError):
        status = 404 if exc.code == "NOT_FOUND" else 400
        return JSONResponse(status_code=status, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION_ERROR", "message": "请求参数不完整或非法。"}})

    @app.exception_handler(Exception)
    async def internal_error_handler(request, exc):
        return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_ERROR", "message": "操作失败，请检查本地目录与数据后重试。"}})

    def _run_task(task_id: str, file_path: str, req: TaskRequest, snapshot, confirmation) -> None:
        try:
            loop.run(
                req.instruction.strip(),
                file_path,
                task_id=task_id,
                field_mapping=req.field_mapping,
                amount_mode=req.amount_mode,
                report_week=req.report_week,
                compare_week=req.compare_week,
                complete=req.complete,
                unit=req.unit,
                input_snapshot=snapshot,
                confirmation=confirmation,
            )
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
        return {"status": "ok", "model_provider": config.model_provider}

    @app.get("/api/v1/diagnostics")
    def diagnostics():
        return diagnose(config)

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
        data = await file.read(file_tools.MAX_FILE_MB * 1024 * 1024 + 1)
        if len(data) > file_tools.MAX_FILE_MB * 1024 * 1024:
            raise WorkmateError("FILE_TOO_LARGE", f"文件超过 {file_tools.MAX_FILE_MB}MB 上限")
        try:
            if Path(name).suffix.lower() == ".csv":
                if b"\x00" in data:
                    raise ValueError("binary CSV")
                pd.read_csv(BytesIO(data), nrows=1)
            else:
                pd.read_excel(BytesIO(data), nrows=1)
        except Exception as exc:
            raise WorkmateError("FILE_PARSE_FAILED", "文件内容不是可读取的表格") from exc
        try:
            with (config.data_dir / name).open("xb") as destination:
                destination.write(data)
        except FileExistsError as exc:
            raise WorkmateError("FILE_EXISTS", "同名文件已存在，请先改名再上传") from exc
        return {"name": name, "size": len(data)}

    @app.post("/api/v1/inspect")
    def inspect_file(req: InspectRequest):
        p = _resolve_input(req.file)
        snapshot = file_tools.read_snapshot(p)
        result = inspect.inspect_file(p, field_mapping=req.field_mapping, snapshot=snapshot)
        mapping = inspect.validate_mapping(snapshot.table(), result["mapping"])
        receipt = loop.storage.save_confirmation(p, snapshot.fingerprint, mapping)
        return {**result, "confirmation_id": receipt["id"]}

    @app.post("/api/v1/tasks")
    def create_task(req: TaskRequest):
        if not (req.instruction and req.instruction.strip()):
            raise WorkmateError("BAD_INSTRUCTION", "请填写任务指令")
        p = _resolve_input(req.file)
        snapshot = file_tools.read_snapshot(p)
        df = snapshot.table()
        if req.field_mapping is not None:
            inspect.validate_mapping(df, req.field_mapping)
        if req.confirmation_id is not None:
            receipt = loop.storage.get_confirmation(req.confirmation_id)
            if receipt is None or receipt.get("file") != str(p.resolve()):
                raise WorkmateError("CONFIRMATION_INVALID", "检查确认信息无效，请返回重新检查当前表格。")
            mapping = inspect.validate_mapping(df, req.field_mapping if req.field_mapping is not None else receipt["field_mapping"])
            if mapping != receipt["field_mapping"]:
                raise WorkmateError("CONFIRMATION_INVALID", "字段与检查时不同，请返回重新检查当前字段。")
            if snapshot.fingerprint != receipt["fingerprint"]:
                raise WorkmateError("SOURCE_CHANGED", "数据表在检查后发生变化，请返回重新检查并确认口径后再生成。")
            mode = "inspected"
        else:
            previous = loop.storage.latest_confirmation(p)
            if previous and previous["fingerprint"] != snapshot.fingerprint:
                raise WorkmateError("SOURCE_CHANGED", "数据表在检查后发生变化，请重新检查并确认口径后再生成。")
            try:
                inferred = req.field_mapping if req.field_mapping is not None else compute.infer_columns(df)
            except WorkmateError as exc:
                if exc.code != "COLUMN_UNKNOWN":
                    raise
                inferred = {}  # 保留旧 v1 缺业务列时返回可追踪 failed 任务的契约
            mapping = inspect.validate_mapping(df, inferred)
            receipt = loop.storage.save_confirmation(p, snapshot.fingerprint, mapping)
            mode = "compatibility_inspection"
        req.field_mapping = mapping
        confirmation = {**receipt, "mode": mode, "amount_mode": req.amount_mode, "unit": req.unit,
                        "report_week": req.report_week, "compare_week": req.compare_week,
                        "complete": req.complete or {}, "confirmed_at": now_iso()}
        task_id = uuid.uuid4().hex[:12]
        loop.storage.save_task(Task(task_id=task_id, status="running", instruction=req.instruction.strip(), input_file=str(p), confirmation=confirmation))
        executor.submit(_run_task, task_id, str(p), req, snapshot, confirmation)
        return {"task_id": task_id, "status": "running", "confirmation_mode": mode}

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

    @app.get("/api/v1/tasks/{task_id}/basis")
    def get_basis(task_id: str):
        p = config.output_dir / task_id / "analysis_basis.json"
        if not p.exists():
            raise WorkmateError("NOT_FOUND", "依据文件不存在")
        return json.loads(p.read_text(encoding="utf-8"))

    @app.get("/api/v1/tasks/{task_id}/facts")
    def get_facts(task_id: str):
        t = loop.storage.load_task(task_id)
        if t is None or not t.result:
            raise WorkmateError("NOT_FOUND", "任务不存在或未完成")
        return {"facts": t.result.get("facts", []), "change_facts": t.result.get("change_facts", [])}

    @app.get("/api/v1/tasks/{task_id}/files/{name:path}")
    def get_file(task_id: str, name: str):
        base = (config.output_dir / task_id).resolve()
        target = (base / name).resolve()
        if not target.is_relative_to(base):
            raise WorkmateError("FORBIDDEN", "非法路径")
        if not target.exists():
            raise WorkmateError("NOT_FOUND", "文件不存在")
        return FileResponse(target)

    # 静态前端（挂载在最后，/api 优先匹配）
    app.mount("/", LocalStaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    return app
