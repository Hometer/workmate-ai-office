from workmate.schemas import Task
from workmate.storage import Storage


def test_task_roundtrip(tmp_path):
    s = Storage(tmp_path)
    t = Task(task_id="abc", instruction="做个周报")
    s.save_task(t)
    loaded = s.load_task("abc")
    assert loaded is not None
    assert loaded.instruction == "做个周报"
    assert loaded.task_id == "abc"


def test_missing_task(tmp_path):
    s = Storage(tmp_path)
    assert s.load_task("nope") is None


def test_trace_appends(tmp_path):
    s = Storage(tmp_path)
    s.append_trace({"ts": "x", "task_id": "a", "step": "read_file"})
    s.append_trace({"ts": "y", "task_id": "a", "step": "compute_metrics"})
    lines = s.trace_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert "schema_version" in lines[0]


def test_recover_interrupted(tmp_path):
    s = Storage(tmp_path)
    s.save_task(Task(task_id="r1", status="running", instruction="x"))
    s.save_task(Task(task_id="d1", status="done", instruction="y"))
    assert s.recover_interrupted() == 1
    r1 = s.load_task("r1")
    assert r1.status == "failed"
    assert r1.error["code"] == "INTERRUPTED"
    assert s.load_task("d1").status == "done"
