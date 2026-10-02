"""持久化：任务状态（tasks.json）+ 轨迹（trace.jsonl）+ 人读日志（app.log），带 schema 版本，原子写入。"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .schemas import Task
from .schemas import WorkmateError, now_iso
from uuid import uuid4

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
        self.confirmations_path = self.state_dir / "confirmations.json"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _load_confirmations(self) -> dict:
        if not self.confirmations_path.exists():
            return {"schema_version": 1, "records": {}, "latest": {}}
        try:
            data = json.loads(self.confirmations_path.read_text(encoding="utf-8"))
            if data.get("schema_version") != 1 or not isinstance(data["records"], dict) or not isinstance(data["latest"], dict):
                raise ValueError("invalid state")
            for key, record in data["records"].items():
                if not isinstance(record, dict) or record.get("id") != key or not isinstance(record.get("file"), str) or not isinstance(record.get("fingerprint"), str) or len(record["fingerprint"]) != 64 or not isinstance(record.get("field_mapping"), dict):
                    raise ValueError("invalid receipt")
            if any(receipt_id not in data["records"] for receipt_id in data["latest"].values()):
                raise ValueError("missing receipt")
            return data
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise WorkmateError("CONFIRMATION_STATE_INVALID", "检查记录无法读取，请恢复状态文件后重新检查；原表和历史成果未改动。") from exc

    def save_confirmation(self, path: Path, fingerprint: str, mapping: dict) -> dict:
        with self._lock:
            state = self._load_confirmations()
            receipt = {"id": uuid4().hex, "file": str(path.resolve()), "fingerprint": fingerprint, "field_mapping": mapping, "inspected_at": now_iso()}
            state["records"][receipt["id"]] = receipt
            state["latest"][receipt["file"]] = receipt["id"]
            _atomic_write(self.confirmations_path, json.dumps(state, ensure_ascii=False, indent=2))
            return receipt

    def get_confirmation(self, receipt_id: str) -> dict | None:
        with self._lock:
            return self._load_confirmations()["records"].get(receipt_id)

    def latest_confirmation(self, path: Path) -> dict | None:
        with self._lock:
            state = self._load_confirmations()
            return state["records"].get(state["latest"].get(str(path.resolve())))

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

    def recover_interrupted(self) -> int:
        """把 stale 的 running 任务标记为"已中断，可重新生成"，返回恢复数量。"""
        from .schemas import StepRecord, now_iso

        with self._lock:
            data = self._load_tasks()
            changed = 0
            for tid, raw in data.items():
                if raw.get("status") == "running":
                    t = Task.model_validate(raw)
                    t.status = "failed"
                    t.error = {"code": "INTERRUPTED", "message": "服务中断，任务未完成，可重新生成。"}
                    t.steps.append(StepRecord(name="recover", status="failed", detail="服务中断", finished_at=now_iso()))
                    t.updated_at = now_iso()
                    data[tid] = t.model_dump()
                    changed += 1
            if changed:
                _atomic_write(self.tasks_path, json.dumps(data, ensure_ascii=False, indent=2))
            return changed

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
