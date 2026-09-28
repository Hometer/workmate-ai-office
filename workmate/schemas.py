"""Pydantic 模型与统一错误结构。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StepRecord(BaseModel):
    name: str
    status: str = "pending"  # pending/running/done/failed/skipped
    detail: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class Task(BaseModel):
    task_id: str
    status: str = "created"  # created/running/done/failed
    instruction: str
    input_file: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    steps: list[StepRecord] = Field(default_factory=list)
    result: Optional[dict[str, Any]] = None


class WorkmateError(Exception):
    """业务错误，带 code + message，对外统一为 {"error": {code, message}}，不泄露堆栈。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}
