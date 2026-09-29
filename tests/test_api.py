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
    assert c.get("/api/v1/health").json() == {"status": "ok", "model_provider": "mock"}


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


def test_upload_rejects_invalid_workbook(tmp_path):
    c, _ = _client(tmp_path)
    r = c.post("/api/v1/upload", files={"file": ("fake.xlsx", b"not an Excel workbook")})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "FILE_PARSE_FAILED"


def test_upload_does_not_overwrite_existing_data(tmp_path):
    c, cfg = _client(tmp_path)
    original = "销售额\n1\n".encode()
    existing = cfg.data_dir / "sales.csv"
    existing.write_bytes(original)
    r = c.post("/api/v1/upload", files={"file": ("sales.csv", "销售额\n2\n".encode())})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "FILE_EXISTS"
    assert existing.read_bytes() == original


def test_create_task_and_poll(tmp_path, sample_df):
    c, cfg = _client(tmp_path)
    sample_df.to_excel(cfg.data_dir / "sales.xlsx", index=False)
    r = c.post("/api/v1/tasks", json={"file": "sales.xlsx", "instruction": "做成销售周报", "amount_mode": "A"})
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
    assert "销售数据汇总" in report
    assert c.get(f"/api/v1/tasks/{task_id}/files/data_summary.xlsx").status_code == 200
    chart = c.get(f"/api/v1/tasks/{task_id}/files/charts%2Ftrend.png")
    assert chart.status_code == 200
    assert chart.headers["content-type"] == "image/png"


def test_create_task_missing_file(tmp_path):
    c, _ = _client(tmp_path)
    r = c.post("/api/v1/tasks", json={"file": "nope.xlsx", "instruction": "做成周报", "amount_mode": "A"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "FILE_NOT_FOUND"


def test_missing_amount_mode_returns_unified_error(tmp_path):
    c, _ = _client(tmp_path)
    r = c.post("/api/v1/tasks", json={"file": "x.xlsx", "instruction": "做成周报"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_failed_task_exposes_structured_reason(tmp_path):
    c, cfg = _client(tmp_path)
    (cfg.data_dir / "bad.csv").write_text("其他列\n1\n", encoding="utf-8")
    created = c.post("/api/v1/tasks", json={"file": "bad.csv", "instruction": "做成周报", "amount_mode": "A"}).json()
    for _ in range(100):
        task = c.get(f"/api/v1/tasks/{created['task_id']}").json()
        if task["status"] == "failed":
            break
        time.sleep(0.05)
    assert task["status"] == "failed"
    assert task["error"]["code"] == "COLUMN_UNKNOWN"
    assert task["error"]["message"]


def test_get_file_not_found(tmp_path):
    c, _ = _client(tmp_path)
    r = c.get("/api/v1/tasks/abc/files/nonexistent.png")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_chart_route_rejects_path_traversal(tmp_path):
    c, cfg = _client(tmp_path)
    (cfg.output_dir / "secret.txt").write_text("private", encoding="utf-8")
    r = c.get("/api/v1/tasks/abc/files/..%2Fsecret.txt")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_index_page_served(tmp_path):
    c, _ = _client(tmp_path)
    r = c.get("/")
    assert r.status_code == 200
    assert "WorkMate" in r.text


def test_inspect_endpoint(tmp_path, sample_df):
    c, cfg = _client(tmp_path)
    sample_df.to_excel(cfg.data_dir / "sales.xlsx", index=False)
    r = c.post("/api/v1/inspect", json={"file": "sales.xlsx"})
    assert r.status_code == 200
    data = r.json()
    assert data["mapping"]["sales"] == "销售额"
    assert data["summary"]["rows"] == 6
    assert "金额口径未确认" in data["blockers"]


def test_task_amount_mode_b(tmp_path):
    import pandas as pd

    c, cfg = _client(tmp_path)
    df = pd.DataFrame({"订单号": ["A", "A", "B"], "销售额": [100, 100, 50]})
    df.to_excel(cfg.data_dir / "s.xlsx", index=False)
    r = c.post("/api/v1/tasks", json={"file": "s.xlsx", "instruction": "做周报", "amount_mode": "B"})
    task_id = r.json()["task_id"]
    status = None
    for _ in range(100):
        status = c.get(f"/api/v1/tasks/{task_id}").json()["status"]
        if status in ("done", "failed"):
            break
        time.sleep(0.05)
    assert status == "done"
    facts = c.get(f"/api/v1/tasks/{task_id}/facts").json()["facts"]
    total = next(f["value"] for f in facts if f["id"] == "total_sales")
    assert total == 150
    basis = c.get(f"/api/v1/tasks/{task_id}/basis").json()
    assert basis["amount_mode"] == "B"
    assert basis["source_fingerprint"]
