"""持久化：任务状态（tasks.json）+ 轨迹（trace.jsonl），带 schema 版本，原子写入。"""
from __future__ import annotations

import json
from pathlib import Path

from .schemas import Task

SCHEMA_VERSION = 1


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class Storage:
    def __init__(self, output_dir: Path):
        self.state_dir = Path(output_dir) / ".workmate"
        self.tasks_path = self.state_dir / "tasks.json"
        self.trace_path = self.state_dir / "trace.jsonl"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def save_task(self, task: Task) -> None:
        data = self._load_tasks()
        data[task.task_id] = task.model_dump()
        _atomic_write(self.tasks_path, json.dumps(data, ensure_ascii=False, indent=2))

    def load_task(self, task_id: str) -> Task | None:
        raw = self._load_tasks().get(task_id)
        return Task.model_validate(raw) if raw else None

    def append_trace(self, event: dict) -> None:
        event = {"schema_version": SCHEMA_VERSION, **event}
        with open(self.trace_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _load_tasks(self) -> dict:
        if self.tasks_path.exists():
            return json.loads(self.tasks_path.read_text(encoding="utf-8"))
        return {}
