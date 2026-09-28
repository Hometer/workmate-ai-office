"""持久化：任务状态（tasks.json）+ 轨迹（trace.jsonl）+ 人读日志（app.log），带 schema 版本，原子写入。"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .schemas import Task

SCHEMA_VERSION = 2


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class Storage:
    def __init__(self, output_dir: Path):
        self.state_dir = Path(output_dir) / ".workmate"
        self.tasks_path = self.state_dir / "tasks.json"
        self.trace_path = self.state_dir / "trace.jsonl"
        self.app_log_path = self.state_dir / "app.log"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save_task(self, task: Task) -> None:
        with self._lock:
            data = self._load_tasks()
            data[task.task_id] = task.model_dump()
            _atomic_write(self.tasks_path, json.dumps(data, ensure_ascii=False, indent=2))

    def load_task(self, task_id: str) -> Task | None:
        with self._lock:
            raw = self._load_tasks().get(task_id)
            return Task.model_validate(raw) if raw else None

    def list_tasks(self) -> list[Task]:
        with self._lock:
            tasks = [Task.model_validate(v) for v in self._load_tasks().values()]
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks

    def append_trace(self, event: dict) -> None:
        event = {"schema_version": SCHEMA_VERSION, **event}
        with self._lock:
            with open(self.trace_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def append_log(self, msg: str) -> None:
        """人读日志：只记文件名/行数/耗时/状态，不记单元格值与个人信息。"""
        from .schemas import now_iso

        with self._lock:
            with open(self.app_log_path, "a", encoding="utf-8") as f:
                f.write(f"{now_iso()} {msg}\n")

    def _load_tasks(self) -> dict:
        if self.tasks_path.exists():
            return json.loads(self.tasks_path.read_text(encoding="utf-8"))
        return {}
