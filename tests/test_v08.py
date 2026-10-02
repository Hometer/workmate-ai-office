"""v0.8 A：数据版本、受控总结、产物口径和启动自检。全部使用合成数据。"""
import json
import time
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workmate.api import create_app
from workmate.loop import Loop
from workmate.schemas import WorkmateError
from workmate.tools import files
from tests.test_review_fixes import cfg


def table(cfg, amount=12):
    p = cfg.data_dir / "sales.csv"
    pd.DataFrame({"日期": ["2026-09-28"], "订单号": ["PRIVATE_ORDER"], "销售额": [amount]}).to_csv(p, index=False)
    return p


def poll(client, tid):
    for _ in range(200):
        task = client.get(f"/api/v1/tasks/{tid}").json()
        if task.get("status") in {"done", "failed"}:
            return task
        time.sleep(.02)
    pytest.fail("task did not terminate")


def test_same_columns_changed_amount_rejects_old_confirmation(cfg):
    table(cfg)
    c = TestClient(create_app(cfg))
    checked = c.post("/api/v1/inspect", json={"file": "sales.csv"}).json()
    table(cfg, 99)
    response = c.post("/api/v1/tasks", json={"file": "sales.csv", "instruction": "生成", "amount_mode": "A", "field_mapping": checked["mapping"], "confirmation_id": checked["confirmation_id"]})
    assert response.status_code == 400 and response.json()["error"]["code"] == "SOURCE_CHANGED"
    assert c.get("/api/v1/tasks").json()["tasks"] == []


@pytest.mark.parametrize("kind", ["forged", "mapping", "file"])
def test_confirmation_cannot_be_reused_for_other_inputs(cfg, kind):
    p = table(cfg)
    c = TestClient(create_app(cfg))
    checked = c.post("/api/v1/inspect", json={"file": p.name}).json()
    body = {"file": p.name, "instruction": "生成", "amount_mode": "A", "field_mapping": checked["mapping"], "confirmation_id": checked["confirmation_id"]}
    if kind == "forged":
        body["confirmation_id"] = "invalid"
    elif kind == "mapping":
        body["field_mapping"] = {"sales": "销售额"}
    else:
        other = cfg.data_dir / "other.csv"
        other.write_bytes(p.read_bytes())
        body["file"] = other.name
    response = c.post("/api/v1/tasks", json=body)
    assert response.status_code == 400 and response.json()["error"]["code"] == "CONFIRMATION_INVALID"


def test_confirmation_survives_restart_and_task_is_immediately_queryable(cfg):
    table(cfg)
    c = TestClient(create_app(cfg))
    checked = c.post("/api/v1/inspect", json={"file": "sales.csv"}).json()
    c = TestClient(create_app(cfg))
    created = c.post("/api/v1/tasks", json={"file": "sales.csv", "instruction": "生成", "amount_mode": "A", "field_mapping": checked["mapping"], "confirmation_id": checked["confirmation_id"]})
    tid = created.json()["task_id"]
    assert c.get(f"/api/v1/tasks/{tid}").status_code == 200
    task = poll(c, tid)
    assert task["status"] == "done"
    assert task["confirmation"]["fingerprint"] == checked["summary"]["fingerprint"]
    assert task["confirmation"]["amount_mode"] == "A"


def test_legacy_client_cannot_reuse_stale_inspection(cfg):
    table(cfg)
    c = TestClient(create_app(cfg))
    c.post("/api/v1/inspect", json={"file": "sales.csv"})
    table(cfg, 44)
    response = c.post("/api/v1/tasks", json={"file": "sales.csv", "instruction": "生成", "amount_mode": "A"})
    assert response.status_code == 400 and response.json()["error"]["code"] == "SOURCE_CHANGED"


def test_task_uses_original_snapshot_when_source_changes_during_calculation(cfg, monkeypatch):
    p = table(cfg)
    original = files.read_snapshot(p)
    loop = Loop(cfg)
    original_compute = __import__("workmate.tools.compute", fromlist=["compute_all"]).compute_all
    def change_source(*args, **kwargs):
        table(cfg, 88)
        return original_compute(*args, **kwargs)
    monkeypatch.setattr("workmate.tools.compute.compute_all", change_source)
    result = loop.run("生成", str(p), amount_mode="A", input_snapshot=original)
    assert next(f["value"] for f in result["facts"] if f["id"] == "total_sales") == 12
    basis = json.loads((Path(result["output_dir"]) / "analysis_basis.json").read_text())
    assert basis["source_fingerprint"] == original.fingerprint


@pytest.mark.parametrize("payload", [
    {"statements": [{"fact_id": "order_count", "value": 9}]},
    {"statements": [{"fact_id": "missing", "value": 1}]},
    {"statements": [{"fact_id": "total_sales", "value": 1}]},
    {"statements": [{"fact_id": "order_count", "value": 1, "text": "因促销大涨"}]},
    {"statements": [{"fact_id": "order_count", "value": 1, "direction": "increase"}]},
    {"statements": []},
    {"statements": [{"fact_id": "order_count", "value": True}]},
    {"statements": [{"fact_id": "order_count", "value": 1}] * 2},
])
def test_fabricated_or_unsupported_summary_is_retried_and_labeled(cfg, payload):
    p = table(cfg)
    loop = Loop(cfg)
    loop.provider.complete = Mock(return_value=json.dumps(payload, ensure_ascii=False))
    result = loop.run("生成", str(p), amount_mode="A")
    assert result["summary_validation"]["status"] == "fallback"
    assert result["summary_validation"]["attempts"] == 3
    assert loop.provider.complete.call_count == 3
    assert "自动降级" in (Path(result["output_dir"]) / "report.md").read_text()


def test_valid_small_integer_and_json_fence_are_accepted(cfg):
    p = table(cfg)
    loop = Loop(cfg)
    loop.provider.complete = Mock(return_value='```json\n{"statements":[{"fact_id":"order_count","value":1}]}\n```')
    result = loop.run("生成", str(p), amount_mode="A", unit="USD")
    assert result["summary_validation"]["status"] == "passed"
    assert result["summary_validation"]["first_pass"] is True
    assert "订单量 1 单 [order_count]" in (Path(result["output_dir"]) / "report.md").read_text()


def test_model_initialization_failure_keeps_verified_results(cfg, monkeypatch):
    p = table(cfg)
    monkeypatch.setattr("workmate.loop.get_provider", Mock(side_effect=RuntimeError("PRIVATE_SECRET")))
    result = Loop(cfg).run("生成", str(p), amount_mode="A")
    assert result["summary_validation"]["status"] == "fallback"
    assert "PRIVATE_SECRET" not in (Path(result["output_dir"]) / "report.md").read_text()


@pytest.mark.parametrize("unit", ["USD", "元", "单位待确认"])
def test_units_scope_and_summary_identity_in_downloads(cfg, unit):
    p = table(cfg)
    result = Loop(cfg).run("生成", str(p), amount_mode="A", unit=unit)
    out = Path(result["output_dir"])
    workbook = pd.ExcelFile(out / "data_summary.xlsx")
    assert "口径与限制" in workbook.sheet_names
    keys = pd.read_excel(workbook, sheet_name="关键指标")
    assert keys.loc[keys["指标"] == "总销售额", "单位"].iloc[0] == unit
    assert set(keys["统计范围"]) == {"全表"}
    basis = json.loads((out / "analysis_basis.json").read_text())
    assert basis["unit_status"] == ("pending" if unit == "单位待确认" else "confirmed")
    assert basis["summary_validation"]["provider"] == "mock"
    report = (out / "report.md").read_text()
    assert "统计范围：全表" in report and f"金额单位：{unit}" in report
    assert "演示模式" in report


def test_mock_diagnostics_is_explicit_and_directories_checked(cfg):
    c = TestClient(create_app(cfg))
    data = c.get("/api/v1/diagnostics").json()
    assert data["model_mode"] == "mock" and data["status"] == "needs_attention"
    assert {x["code"] for x in data["checks"]} >= {"data_directory", "output_directory", "model"}
    assert next(x for x in data["checks"] if x["code"] == "model")["status"] == "pending"
    assert not list(cfg.output_dir.glob(".workmate-probe-*"))


def test_local_diagnostics_handles_unavailable_and_missing_model(cfg, monkeypatch):
    cfg.model_provider = "ollama"
    c = TestClient(create_app(cfg))
    monkeypatch.setattr("workmate.diagnostics.requests.get", Mock(side_effect=ConnectionError("PRIVATE_SECRET")))
    missing = c.get("/api/v1/diagnostics").json()
    assert missing["status"] == "needs_attention" and "PRIVATE_SECRET" not in json.dumps(missing)
    response = Mock(status_code=200)
    response.json.return_value = {"models": []}
    monkeypatch.setattr("workmate.diagnostics.requests.get", Mock(return_value=response))
    assert "下载" in json.dumps(c.get("/api/v1/diagnostics").json(), ensure_ascii=False)
    response.json.return_value = {"models": [{"name": cfg.ollama_model}]}
    assert c.get("/api/v1/diagnostics").json()["status"] == "ready"


def test_diagnostics_never_probes_remote_host(cfg, monkeypatch):
    cfg.model_provider = "ollama"
    cfg.ollama_host = "https://example.com"
    request = Mock()
    monkeypatch.setattr("workmate.diagnostics.requests.get", request)
    assert TestClient(create_app(cfg)).get("/api/v1/diagnostics").json()["status"] == "needs_attention"
    request.assert_not_called()


@pytest.mark.parametrize("value,direction,accepted", [(10, "increase", True), (-10, "decrease", True), (0, "flat", True), (-10, "increase", False), (10, "decrease", False), (0, "increase", False)])
def test_direction_matches_referenced_fact(value, direction, accepted):
    from workmate.summary import validate_and_render
    facts = [{"id": "mom_growth", "value": value, "label": "环比增长率", "unit": "%", "verified": True}]
    raw = json.dumps({"statements": [{"fact_id": "mom_growth", "value": value, "direction": direction}]})
    if accepted:
        assert "[mom_growth]" in validate_and_render(raw, facts)
    else:
        with pytest.raises(ValueError):
            validate_and_render(raw, facts)


@pytest.mark.parametrize("raw", [
    '{"statements":[{"fact_id":"total_sales","value":12,"value":99}]}',
    '{"statements":[{"fact_id":"total_sales","value":NaN}]}',
    '{"statements":[{"fact_id":"total_sales","value":"12"}]}',
    '说明：{"statements":[{"fact_id":"total_sales","value":12}]}',
    '{"statements":[{"fact_id":"total_sales","value":12}],"reason":"促销"}',
])
def test_summary_rejects_ambiguous_or_unstructured_output(raw):
    from workmate.summary import validate_and_render
    with pytest.raises(ValueError):
        validate_and_render(raw, [{"id": "total_sales", "value": 12, "label": "总销售额", "unit": "元", "verified": True}])


def test_summary_only_uses_verified_facts_and_exact_display_precision():
    from workmate.summary import validate_and_render
    facts = [{"id": "total_sales", "value": 12.35, "label": "总销售额", "unit": "USD", "verified": False}]
    raw = '{"statements":[{"fact_id":"total_sales","value":12.35}]}'
    with pytest.raises(ValueError):
        validate_and_render(raw, facts)
    facts[0]["verified"] = True
    assert "12.35 USD" in validate_and_render(raw, facts)
    with pytest.raises(ValueError):
        validate_and_render(raw.replace("12.35", "12.345"), facts)


def test_retry_success_records_first_pass_separately(cfg):
    p = table(cfg)
    loop = Loop(cfg)
    loop.provider.complete = Mock(side_effect=["invalid", '{"statements":[{"fact_id":"total_sales","value":12}]}'])
    result = loop.run("生成", str(p), amount_mode="A")
    meta = result["summary_validation"]
    assert meta["status"] == "passed" and meta["attempts"] == 2 and meta["first_pass"] is False


def test_directory_probe_failure_has_recovery_steps(cfg, monkeypatch):
    monkeypatch.setattr("workmate.diagnostics.tempfile.TemporaryFile", Mock(side_effect=PermissionError("PRIVATE_SECRET")))
    data = TestClient(create_app(cfg)).get("/api/v1/diagnostics").json()
    assert data["status"] == "needs_attention"
    assert all(x["status"] == "failed" and x["steps"] for x in data["checks"][:2])
    assert "PRIVATE_SECRET" not in json.dumps(data)


def test_confirmation_state_corruption_does_not_allow_generation(cfg):
    table(cfg)
    c = TestClient(create_app(cfg), raise_server_exceptions=False)
    state = cfg.output_dir / ".workmate" / "confirmations.json"
    state.write_text("not JSON")
    response = c.post("/api/v1/tasks", json={"file": "sales.csv", "instruction": "生成", "amount_mode": "A"})
    assert response.status_code == 400 and response.json()["error"]["code"] == "CONFIRMATION_STATE_INVALID"
    assert c.get("/api/v1/tasks").json()["tasks"] == []


@pytest.mark.parametrize("value", [None, "", "not-a-currency", "XYZ"])
def test_empty_or_unknown_currency_does_not_become_confirmed(cfg, value):
    p = cfg.data_dir / "currency.csv"
    pd.DataFrame({"销售额": [12], "币种": [value]}).to_csv(p, index=False)
    result = Loop(cfg).run("生成", str(p), amount_mode="A")
    basis = json.loads((Path(result["output_dir"]) / "analysis_basis.json").read_text())
    assert basis["unit"] == "单位待确认" and basis["unit_status"] == "pending"


def test_claimed_week_without_date_is_rejected(cfg):
    p = cfg.data_dir / "no-date.csv"
    p.write_text("销售额\n12\n")
    with pytest.raises(WorkmateError) as err:
        Loop(cfg).run("生成", str(p), amount_mode="A", report_week="2026-09-28")
    assert err.value.code == "REPORT_SCOPE_INVALID"


def test_model_receives_anonymous_dimensions_but_report_keeps_local_facts(cfg):
    p = cfg.data_dir / "private.csv"
    pd.DataFrame({"销售额": [12], "客户姓名": ["私人客户甲"], "客户电话": ["13800000000"]}).to_csv(p, index=False)
    loop = Loop(cfg)
    loop.provider.complete = Mock(return_value='{"statements":[{"fact_id":"top5","value":["商品1"]}]}')
    result = loop.run("生成", str(p), amount_mode="A", field_mapping={"sales": "销售额", "product": "客户姓名", "channel": "客户电话"})
    model_input = loop.provider.complete.call_args.args[1]
    assert "私人客户甲" not in model_input and "13800000000" not in model_input and "客户姓名" not in model_input
    assert result["summary_validation"]["status"] == "passed"
    assert "私人客户甲" in (Path(result["output_dir"]) / "report.md").read_text()


def test_xlsx_user_text_is_not_interpreted_as_formula(cfg):
    import openpyxl
    p = table(cfg)
    result = Loop(cfg).run("生成", str(p), amount_mode="A", unit="=1+1")
    workbook = openpyxl.load_workbook(Path(result["output_dir"]) / "data_summary.xlsx")
    assert not any(cell.data_type == "f" for sheet in workbook for row in sheet for cell in row)


@pytest.mark.parametrize("code", ["MODEL_TIMEOUT", "MODEL_UNAVAILABLE"])
def test_model_call_failure_preserves_numbers_without_sensitive_exception(cfg, code):
    p = table(cfg)
    loop = Loop(cfg)
    loop.provider.complete = Mock(side_effect=WorkmateError(code, "PRIVATE_SECRET"))
    result = loop.run("生成", str(p), amount_mode="A")
    assert result["summary_validation"]["status"] == "fallback" and result["summary_validation"]["attempts"] == 1
    assert result["facts"][0]["value"] == 12
    assert "PRIVATE_SECRET" not in json.dumps(result) + (Path(result["output_dir"]) / "report.md").read_text()


def test_ollama_requests_json_and_rejects_unfinished_response(monkeypatch):
    from workmate.model.ollama import OllamaProvider
    response = Mock(status_code=200)
    response.json.return_value = {"done": True, "message": {"content": '{"statements":[]}'}}
    request = Mock(return_value=response)
    monkeypatch.setattr("workmate.model.ollama.requests.post", request)
    provider = OllamaProvider("http://localhost:11434", "qwen2.5:7b")
    assert provider.complete("system", "facts") == '{"statements":[]}'
    assert request.call_args.kwargs["json"]["format"] == "json"
    assert request.call_args.kwargs["allow_redirects"] is False
    response.json.return_value["done"] = False
    with pytest.raises(WorkmateError) as err:
        provider.complete("system", "facts")
    assert err.value.code == "MODEL_ERROR"


def test_ollama_blocks_remote_calls_and_redirects(monkeypatch):
    from workmate.model.ollama import OllamaProvider
    response = Mock(status_code=302)
    request = Mock(return_value=response)
    monkeypatch.setattr("workmate.model.ollama.requests.post", request)
    with pytest.raises(WorkmateError):
        OllamaProvider("https://example.com", "qwen").complete("system", "PRIVATE_DATA")
    request.assert_not_called()
    with pytest.raises(WorkmateError):
        OllamaProvider("http://localhost:11434", "qwen").complete("system", "PRIVATE_DATA")


def test_confirmed_snapshot_survives_external_source_removal(cfg):
    p = table(cfg)
    snapshot = files.read_snapshot(p)
    loop = Loop(cfg)
    mapping = {"sales": "销售额", "date": "日期", "order": "订单号"}
    receipt = loop.storage.save_confirmation(p, snapshot.fingerprint, mapping)
    p.unlink()  # 只删除本测试的合成文件，模拟提交后的外部动作
    result = loop.run("生成", str(p), amount_mode="A", input_snapshot=snapshot, confirmation=receipt, field_mapping=mapping)
    assert result["facts"][0]["value"] == 12


def test_background_parameters_cannot_change_after_confirmation(cfg):
    p = table(cfg)
    snapshot = files.read_snapshot(p)
    loop = Loop(cfg)
    mapping = {"sales": "销售额", "order": "订单号", "date": "日期"}
    receipt = loop.storage.save_confirmation(p, snapshot.fingerprint, mapping)
    receipt["amount_mode"] = "B"
    with pytest.raises(WorkmateError) as err:
        loop.run("生成", str(p), amount_mode="A", field_mapping=mapping, input_snapshot=snapshot, confirmation=receipt)
    assert err.value.code == "CONFIRMATION_INVALID"
    assert loop.storage.list_tasks()[0].status == "failed"


def test_new_assets_have_consistent_versioned_urls(cfg):
    client = TestClient(create_app(cfg))
    html = client.get("/").text
    assert 'styles.css?v=0.8-workspace1' in html and 'app.js?v=0.8-workspace1' in html
    assert client.get('/styles.css?v=0.8-workspace1').headers['cache-control'] == 'no-cache'
    assert './api.js?v=0.8-workspace1' in client.get('/app.js?v=0.8-workspace1').text


def test_cli_startup_directory_error_is_readable_without_traceback(cfg, monkeypatch, capsys):
    from workmate.cli import main
    monkeypatch.setattr("workmate.cli.load_config", Mock(return_value=cfg))
    monkeypatch.setattr("workmate.cli.Loop", Mock(side_effect=PermissionError("PRIVATE_SECRET")))
    assert main(["resume", "--task-id", "unknown"]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["error"]["code"] == "LOCAL_STATE_UNAVAILABLE"
    assert "PRIVATE_SECRET" not in output and "Traceback" not in output


@pytest.mark.parametrize("raw", [
    '{"statements":[{"fact_id":"total_sales","value":' + '9' * 400 + '}]}',
    '[' * 2000 + '0' + ']' * 2000,
])
def test_extreme_model_json_retries_then_falls_back(cfg, raw):
    p = table(cfg)
    loop = Loop(cfg)
    loop.provider = Mock()
    loop.provider.chat.return_value = raw
    result = loop.run("生成", str(p), amount_mode="A")
    assert result["summary_validation"]["attempts"] == 3
    assert result["summary_validation"]["status"] == "fallback"
    assert loop.storage.list_tasks()[0].status == "done"


@pytest.mark.parametrize("value", ["inf", "-Infinity"])
def test_nonfinite_sales_are_blocked_in_inspection_and_calculation(cfg, value):
    p = table(cfg, value)
    client = TestClient(create_app(cfg))
    checked = client.post("/api/v1/inspect", json={"file": p.name})
    assert checked.status_code == 200
    assert checked.json()["quality"]["sales"]["unparseable"] == 1
    assert checked.json()["blockers"]
    from workmate.tools import compute, verify
    df = pd.DataFrame({"销售额": [value]})
    for convert in [compute._to_numeric_sales, verify._to_numeric_independent]:
        with pytest.raises(WorkmateError) as err:
            convert(df, "销售额")
        assert err.value.code == "BAD_SALES_VALUE"
    with pytest.raises(WorkmateError):
        Loop(cfg).run("生成", str(p), amount_mode="A")


def test_independent_check_never_accepts_nonfinite_aggregates():
    from workmate.tools.verify import _close
    assert not _close(float("inf"), float("inf"))
    assert not _close(float("inf"), 12)
    assert not _close(float("nan"), float("nan"))
