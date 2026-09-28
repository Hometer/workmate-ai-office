import time

from fastapi.testclient import TestClient

from workmate.api import create_app
from workmate.config import Config


def _client(tmp_path):
    cfg = Config(
        {
            "data_dir": tmp_path / "data",
            "output_dir": tmp_path / "outputs",
            "model_provider": "mock",
            "ollama_host": "http://localhost:11434",
            "ollama_model": "qwen2.5:7b",
        }
    )
    cfg.ensure_dirs()
    return TestClient(create_app(cfg)), cfg


def test_health(tmp_path):
    c, _ = _client(tmp_path)
    assert c.get("/api/v1/health").json() == {"status": "ok"}


def test_upload_and_list_files(tmp_path):
    c, _ = _client(tmp_path)
    r = c.post("/api/v1/upload", files={"file": ("sales.csv", "销售额\n1\n2\n".encode(), "text/csv")})
    assert r.status_code == 200
    assert r.json()["name"] == "sales.csv"
    names = [f["name"] for f in c.get("/api/v1/data-files").json()["files"]]
    assert "sales.csv" in names


def test_upload_rejects_bad_ext(tmp_path):
    c, _ = _client(tmp_path)
    r = c.post("/api/v1/upload", files={"file": ("x.txt", b"hi", "text/plain")})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "UNSUPPORTED_FILE"


def test_create_task_and_poll(tmp_path, sample_df):
    c, cfg = _client(tmp_path)
    sample_df.to_excel(cfg.data_dir / "sales.xlsx", index=False)
    r = c.post("/api/v1/tasks", json={"file": "sales.xlsx", "instruction": "做成销售周报"})
    assert r.status_code == 200
    task_id = r.json()["task_id"]
    assert r.json()["status"] == "running"

    status = None
    for _ in range(100):
        status = c.get(f"/api/v1/tasks/{task_id}").json()["status"]
        if status in ("done", "failed"):
            break
        time.sleep(0.05)
    assert status == "done"

    report = c.get(f"/api/v1/tasks/{task_id}/report").json()["report"]
    assert "销售数据周报" in report
    assert c.get(f"/api/v1/tasks/{task_id}/files/data_summary.xlsx").status_code == 200


def test_create_task_missing_file(tmp_path):
    c, _ = _client(tmp_path)
    r = c.post("/api/v1/tasks", json={"file": "nope.xlsx", "instruction": "做成周报"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "FILE_NOT_FOUND"


def test_get_file_not_found(tmp_path):
    c, _ = _client(tmp_path)
    r = c.get("/api/v1/tasks/abc/files/nonexistent.png")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_index_page_served(tmp_path):
    c, _ = _client(tmp_path)
    r = c.get("/")
    assert r.status_code == 200
    assert "WorkMate" in r.text
