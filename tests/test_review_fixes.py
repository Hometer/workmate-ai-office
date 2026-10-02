"""M3.7：拒交归属不清的周金额，并校验所有入口的字段映射。"""
import json
import time
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workmate.api import create_app
from workmate.config import Config
from workmate.loop import Loop
from workmate.schemas import WorkmateError


@pytest.fixture
def cfg(tmp_path):
    config = Config({
        "data_dir": tmp_path / "data", "output_dir": tmp_path / "outputs",
        "model_provider": "mock", "ollama_host": "http://localhost:11434",
        "ollama_model": "qwen2.5:7b",
    })
    config.ensure_dirs()
    return config


def _table(cfg, dates, orders, amounts):
    p = cfg.data_dir / "sales.csv"
    pd.DataFrame({"日期": dates, "订单号": orders, "销售额": amounts}).to_csv(p, index=False)
    return p


@pytest.mark.parametrize("earlier", ["2026-09-21", "2026-09-07"])
def test_ambiguous_report_week_has_no_verified_result_or_model_call(cfg, earlier):
    p = _table(cfg, [earlier, "2026-09-28"], ["  PRIVATE_ORDER ", "PRIVATE_ORDER"], [100, 100])
    before = p.read_bytes()
    loop = Loop(cfg)
    loop.provider.complete = Mock(side_effect=AssertionError("must not call model"))
    with pytest.raises(WorkmateError) as err:
        loop.run("生成", str(p), amount_mode="B", report_week="2026-09-28")
    assert err.value.code == "ORDER_WEEK_AMBIGUOUS"
    assert "PRIVATE_ORDER" not in err.value.message
    loop.provider.complete.assert_not_called()
    saved = Loop(cfg).storage.list_tasks()[0]
    assert saved.status == "failed" and saved.result is None
    assert saved.error["code"] == "ORDER_WEEK_AMBIGUOUS"
    assert not (cfg.output_dir / saved.task_id).exists()
    assert p.read_bytes() == before


def test_ambiguous_compare_week_is_not_verified(cfg):
    p = _table(cfg, ["2026-09-14", "2026-09-21", "2026-09-28"], ["X", "X", "Y"], [100, 100, 50])
    result = Loop(cfg).run("生成", str(p), amount_mode="B", report_week="2026-09-28", complete={"report": True, "compare": True})
    assert next(f["value"] for f in result["facts"] if f["id"] == "total_sales") == 50
    assert all(f["id"] != "mom_growth" for f in result["facts"])
    assert result["change_facts"] == []
    basis = json.loads((Path(result["output_dir"]) / "analysis_basis.json").read_text())
    assert basis["verify"]["report"] is True and basis["verify"]["compare"] is False
    assert basis["compare_unavailable_reason"]
    assert "对比周" in (Path(result["output_dir"]) / "report.md").read_text()


def test_cross_week_orders_outside_selected_weeks_do_not_block_report(cfg):
    p = _table(cfg, ["2026-08-31", "2026-09-07", "2026-09-21", "2026-09-28"], ["X", "X", "Y", "Z"], [100, 100, 20, 50])
    result = Loop(cfg).run("生成", str(p), amount_mode="B", report_week="2026-09-28")
    assert next(f["value"] for f in result["facts"] if f["id"] == "total_sales") == 50


@pytest.mark.parametrize("mode,report_week,total", [("B", None, 150), ("A", "2026-09-28", 150)])
def test_cross_week_summary_and_row_amount_mode_remain_available(cfg, mode, report_week, total):
    p = _table(cfg, ["2026-09-21", "2026-09-28", "2026-09-29"], ["X", "X", "Y"], [100, 100, 50])
    result = Loop(cfg).run("生成", str(p), amount_mode=mode, report_week=report_week)
    assert next(f["value"] for f in result["facts"] if f["id"] == "total_sales") == total


def test_b_order_on_multiple_days_in_same_week_remains_available(cfg):
    p = _table(cfg, ["2026-09-28", "2026-09-29", "2026-09-30"], ["X", "X", "Y"], [100, 100, 50])
    result = Loop(cfg).run("生成", str(p), amount_mode="B", report_week="2026-09-28")
    assert next(f["value"] for f in result["facts"] if f["id"] == "total_sales") == 150


@pytest.mark.parametrize("endpoint", ["inspect", "tasks"])
@pytest.mark.parametrize("mapping", [
    *[{"sales": "销售额", key: "PRIVATE_MISSING_COLUMN"} for key in ["sales", "date", "product", "channel", "order"]],
    {"sales": ["销售额"]}, {"sales": 123}, {"sales": True},
    {"sales": "销售额", "PRIVATE_UNKNOWN_ROLE": "订单号"},
])
def test_invalid_mapping_returns_business_error_before_task_submission(cfg, endpoint, mapping):
    _table(cfg, ["2026-09-28"], ["X"], [100])
    client = TestClient(create_app(cfg), raise_server_exceptions=False)
    response = client.post(f"/api/v1/{endpoint}", json={
        "file": "sales.csv", "instruction": "生成", "amount_mode": "A", "field_mapping": mapping,
    })
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "FIELD_MAPPING_INVALID"
    assert set(body["error"]) == {"code", "message"}
    assert "PRIVATE_" not in response.text
    assert client.get("/api/v1/tasks").json()["tasks"] == []


def test_loop_cannot_bypass_mapping_validation(cfg):
    p = _table(cfg, ["2026-09-28"], ["X"], [100])
    loop = Loop(cfg)
    with pytest.raises(WorkmateError) as err:
        loop.run("生成", str(p), amount_mode="A", field_mapping={"sales": "PRIVATE_MISSING_COLUMN"})
    assert err.value.code == "FIELD_MAPPING_INVALID"
    saved = Loop(cfg).storage.list_tasks()[0]
    assert saved.error["code"] == "FIELD_MAPPING_INVALID"
    assert saved.status == "failed" and saved.result is None
    assert "PRIVATE_" not in loop.storage.app_log_path.read_text()


def test_optional_unmapped_fields_and_explicit_empty_mapping(cfg):
    _table(cfg, ["2026-09-28"], ["X"], [100])
    client = TestClient(create_app(cfg))
    response = client.post("/api/v1/inspect", json={"file": "sales.csv", "field_mapping": {"sales": "销售额", "date": None, "order": ""}})
    assert response.status_code == 200 and response.json()["mapping"] == {"sales": "销售额"}
    empty = client.post("/api/v1/inspect", json={"file": "sales.csv", "field_mapping": {}})
    assert empty.status_code == 200 and "缺少销售额列" in empty.json()["blockers"]


def test_api_ambiguous_week_failure_is_structured_and_persisted(cfg):
    _table(cfg, ["2026-09-21", "2026-09-28"], ["X", "X"], [100, 100])
    client = TestClient(create_app(cfg))
    created = client.post("/api/v1/tasks", json={"file": "sales.csv", "instruction": "生成", "amount_mode": "B", "report_week": "2026-09-28"})
    task_id = created.json()["task_id"]
    for _ in range(100):
        task = client.get(f"/api/v1/tasks/{task_id}").json()
        if task["status"] in ("failed", "done"):
            break
        time.sleep(.02)
    assert task["status"] == "failed" and task["error"]["code"] == "ORDER_WEEK_AMBIGUOUS"
    assert client.get(f"/api/v1/tasks/{task_id}/report").status_code == 404
    restarted = TestClient(create_app(cfg))
    assert restarted.get(f"/api/v1/tasks/{task_id}").json()["error"] == task["error"]


@pytest.mark.parametrize("path", ["/", "/app.js", "/api.js", "/styles.css"])
def test_static_resources_revalidate_after_service_updates(cfg, path):
    client = TestClient(create_app(cfg))
    first = client.get(path)
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-cache"
    unchanged = client.get(path, headers={"If-None-Match": first.headers["etag"]})
    assert unchanged.status_code == 304 and unchanged.headers["cache-control"] == "no-cache"
