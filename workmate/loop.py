"""s01 Agent loop：编排 v0.6 主链路（检查/口径/周 → 计算 → 双周独立核对 → 事实 → 总结 → 落盘）。"""
from __future__ import annotations

import json
import time
import threading
from pathlib import Path
from uuid import uuid4

import pandas as pd

from . import basis as basis_mod
from . import facts as facts_mod
from . import inspect
from . import amounts
from . import weeks
from . import summary as summary_mod
from .config import Config
from .knowledge import report_templates
from .model import get_provider
from .schemas import StepRecord, Task, WorkmateError, now_iso
from .storage import Storage
from .tools import compute, files, plot, safety, verify

SUMMARY_SYSTEM = summary_mod.SYSTEM

METRIC_FORMULA_VERSION = "2026-09-29-v06-1"
_PLOT_LOCK = threading.Lock()


def _facts_text(facts: list[dict]) -> str:
    return json.dumps(facts, ensure_ascii=False, indent=2)


class Loop:
    def __init__(self, config: Config):
        self.config = config
        self.storage = Storage(config.output_dir)
        self.provider = None
        try:
            self.provider = get_provider(config)
        except Exception:
            # 初始化失败也能交付已核对的确定性报告，不记录异常原文。
            pass

    def run(
        self,
        instruction: str,
        file_path: str | None = None,
        overwrite: bool = False,
        task_id: str | None = None,
        *,
        field_mapping: dict | None = None,
        amount_mode: str | None = None,
        report_week: str | None = None,
        compare_week: str | None = None,
        complete: dict | None = None,
        unit: str | None = None,
        input_snapshot: files.TableSnapshot | None = None,
        confirmation: dict | None = None,
    ) -> dict:
        config = self.config
        config.ensure_dirs()
        if not (instruction and instruction.strip()):
            raise WorkmateError("BAD_INSTRUCTION", "请给一句任务指令，例如：把 sales.xlsx 做成销售周报。")
        if amount_mode not in ("A", "B"):
            raise WorkmateError("AMOUNT_MODE_REQUIRED", "请明确选择金额口径 A 或 B，不能默认。")

        task = Task(task_id=task_id or uuid4().hex[:12], instruction=instruction, input_file=file_path or "")
        task.status = "running"
        task.confirmation = confirmation or {}
        self.storage.save_task(task)
        self.storage.append_log(f"[task {task.task_id}] 开始")
        t0 = time.time()

        try:
            result = self._execute(task, file_path, overwrite, field_mapping, amount_mode, report_week, compare_week, complete, unit, input_snapshot)
            if self.config.model_provider == "mock":
                result["changes"] += "（开发期 mock 模式：总结为占位文本，未调用真实模型。）"
                self.storage.append_log("[task] mock 模式，未调用真实模型")
            task.status = "done"
            task.result = result
            task.updated_at = now_iso()
            self.storage.save_task(task)
            self.storage.append_log(f"[task {task.task_id}] 完成，交付时长 {time.time() - t0:.2f}s")
            return result
        except WorkmateError as e:
            task.status = "failed"
            task.error = e.to_dict()["error"]
            task.updated_at = now_iso()
            self.storage.save_task(task)
            self.storage.append_log(f"[task {task.task_id}] 失败：{e.code}")
            raise
        except Exception as e:  # noqa: BLE001
            error = WorkmateError("INTERNAL_ERROR", "任务执行失败，请检查输入后重试")
            task.status = "failed"
            task.error = error.to_dict()["error"]
            task.updated_at = now_iso()
            self.storage.save_task(task)
            self.storage.append_log(f"[task {task.task_id}] 失败：{error.code}")
            raise error from e

    def _execute(self, task, file_path, overwrite, field_mapping, amount_mode, report_week, compare_week, complete, unit, input_snapshot=None):
        config = self.config

        if input_snapshot is not None and task.confirmation:
            input_path = Path(task.confirmation.get("file", "")).resolve()
            if not input_path.is_relative_to(config.data_dir.resolve()):
                raise WorkmateError("CONFIRMATION_INVALID", "确认记录中的文件不属于授权目录，请重新检查。")
        else:
            input_path = self._locate(file_path)
        task.input_file = str(input_path)
        self._step(task, "search_files", "done", str(input_path))

        snapshot = input_snapshot or files.read_snapshot(input_path)
        full_df = snapshot.table()
        schema = files.describe_schema(full_df)
        self._step(task, "read_file", "done", f"shape={schema['shape']}")

        mapping = inspect.validate_mapping(full_df, field_mapping if field_mapping is not None else compute.infer_columns(full_df))
        if "sales" not in mapping:
            raise WorkmateError("COLUMN_UNKNOWN", "缺少销售额列，无法计算。")
        self._step(task, "infer_columns", "done", str(mapping))
        if not task.confirmation:
            previous = self.storage.latest_confirmation(input_path)
            if previous and previous["fingerprint"] != snapshot.fingerprint:
                raise WorkmateError("SOURCE_CHANGED", "数据表在检查后发生变化，请重新检查并确认口径。")
            receipt = self.storage.save_confirmation(input_path, snapshot.fingerprint, mapping)
            task.confirmation = {**receipt, "mode": "compatibility_inspection", "amount_mode": amount_mode, "unit": unit,
                                 "report_week": report_week, "compare_week": compare_week, "complete": complete or {}, "confirmed_at": now_iso()}
        if task.confirmation.get("fingerprint") != snapshot.fingerprint or task.confirmation.get("field_mapping") != mapping:
            raise WorkmateError("CONFIRMATION_INVALID", "生成输入与确认记录不一致，请重新检查。")
        confirmed_parameters = {"amount_mode": amount_mode, "unit": unit, "report_week": report_week,
                                "compare_week": compare_week, "complete": complete or {}}
        if any(key in task.confirmation and task.confirmation[key] != value for key, value in confirmed_parameters.items()):
            raise WorkmateError("CONFIRMATION_INVALID", "统计口径与确认记录不一致，请重新检查并确认。")
        task.confirmation.update(confirmed_parameters)
        if complete and (set(complete) - {"report", "compare"} or any(type(v) is not bool for v in complete.values())):
            raise WorkmateError("CONFIRMATION_INVALID", "数据完整性须由本次人工确认，请重新检查。")
        self._step(task, "confirm_input", "done", "本次数据版本与口径已保存")

        # G10 币种：多币种阻断
        currency_col, currency_distinct = inspect.detect_currency(full_df)
        if currency_distinct > 1:
            raise WorkmateError("MULTI_CURRENCY", f"币种列（{currency_col}）有 {currency_distinct} 种币种，不能混算。")

        # P0-1 全表销售额检查（报告/对比周之外的坏值也要阻断）
        compute._to_numeric_sales(full_df, mapping["sales"])

        report_monday = weeks.parse_monday(report_week)
        if report_monday and not mapping.get("date"):
            raise WorkmateError("REPORT_SCOPE_INVALID", "按周统计需要有效日期字段；请重新检查日期或选择全表汇总。")

        # G8 对比周由后端推导并校验相邻
        compare_monday = None
        if report_monday and mapping.get("date"):
            expected_compare = weeks.previous_week(report_monday)
            client_compare = weeks.parse_monday(compare_week) if compare_week else None
            if client_compare is not None and client_compare != expected_compare:
                raise WorkmateError("COMPARE_WEEK_INVALID", "对比周必须是报告周的上一自然周。")
            compare_monday = expected_compare

        # G4 周模式下日期空/坏值阻断（不静默过滤）
        if report_monday and mapping.get("date"):
            raw_date = full_df[mapping["date"]]
            d_all = pd.to_datetime(raw_date, errors="coerce")
            empty_or_bad = raw_date.isna() | (raw_date.astype(str).str.strip() == "") | d_all.isna()
            if int(empty_or_bad.sum()) > 0:
                raise WorkmateError(
                    "BAD_DATE_VALUE",
                    f"日期列有 {int(empty_or_bad.sum())} 个空值或无法解析的值，请修正后重试，或改用'销售数据汇总'（不按周筛选）。",
                )

        ambiguous_weeks = amounts.ambiguous_order_weeks(full_df, mapping) if amount_mode == "B" else set()
        cross_week = bool(ambiguous_weeks)
        if report_monday in ambiguous_weeks:
            raise WorkmateError(
                "ORDER_WEEK_AMBIGUOUS",
                "报告周包含跨周订单，金额归属不明确。请修正订单日期归属，或返回检查页将日期列设为不指定，改做全表汇总。",
            )

        report_df = weeks.filter_to_week(full_df, mapping["date"], report_monday) if (report_monday and mapping.get("date")) else full_df
        if len(report_df) == 0:
            raise WorkmateError("REPORT_WEEK_EMPTY", "所选报告周没有记录，请选择有记录的报告周。")
        report_metrics = compute.compute_all(report_df, mapping, amount_mode)

        compare_metrics = None
        compare_empty = False
        compare_unavailable_reason = None
        if compare_monday and mapping.get("date"):
            compare_df = weeks.filter_to_week(full_df, mapping["date"], compare_monday)
            if len(compare_df) == 0:
                compare_empty = True
            elif compare_monday in ambiguous_weeks:
                compare_unavailable_reason = "对比周包含跨周订单，金额归属不明确，未计算或核对该周金额。"
            else:
                compare_metrics = compute.compute_all(compare_df, mapping, amount_mode)

        if report_metrics["mom_growth"] is None and compare_metrics is not None and (complete or {}).get("report") and (complete or {}).get("compare") and not cross_week:
            prev = compare_metrics["total_sales"]
            if prev and prev != 0:
                report_metrics["mom_growth"] = (report_metrics["total_sales"] - prev) / prev
        if cross_week:
            report_metrics.setdefault("warnings", []).append("表中部分订单跨自然周，跨周比较暂不可用。")
        if compare_unavailable_reason:
            report_metrics.setdefault("warnings", []).append(compare_unavailable_reason)
        if compare_empty:
            report_metrics.setdefault("warnings", []).append("对比周无记录，无法比较。")
        self._step(task, "compute_metrics", "done", f"总销售额={report_metrics['total_sales']:,.2f}")

        # G9 独立核对：报告周 + 对比周都要通过
        issues = verify.verify_metrics(snapshot.table(), mapping, report_metrics, amount_mode, report_monday)
        if issues:
            self._step(task, "verify_metrics", "failed", json.dumps(issues, ensure_ascii=False))
            raise WorkmateError("VERIFY_FAILED", "数字核对不一致：" + json.dumps(issues, ensure_ascii=False))
        if compare_metrics is not None:
            c_issues = verify.verify_metrics(snapshot.table(), mapping, compare_metrics, amount_mode, compare_monday)
            if c_issues:
                self._step(task, "verify_metrics", "failed", json.dumps(c_issues, ensure_ascii=False))
                raise WorkmateError("VERIFY_FAILED", "对比周数字核对不一致：" + json.dumps(c_issues, ensure_ascii=False))
        self._step(task, "verify_metrics", "done", "数字核对一致（报告周+对比周）" if compare_metrics is not None else "数字核对一致（本次统计范围；未核对对比周）")

        # P0-8 有日期但未选报告周 → 汇总模式（无环比）
        has_date = bool(mapping.get("date"))
        is_summary_mode = (not has_date) or (has_date and report_monday is None)
        recognized_unit = inspect.currency_display_unit(full_df)
        unit = recognized_unit or unit or "单位待确认"
        unit_source = "field" if recognized_unit else "pending" if unit == "单位待确认" else "user"
        if is_summary_mode:
            report_metrics["mom_growth"] = None

        task_out = config.output_dir / task.task_id
        charts_dir = task_out / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)
        context = {
            "scope": "全表" if is_summary_mode else f"报告周 {report_monday} ~ {report_monday + pd.Timedelta(days=6)}",
            "unit": unit, "unit_source": unit_source,
            "unit_status": "pending" if unit == "单位待确认" else "confirmed",
            "amount_mode": amount_mode, "report_week": report_week,
            "compare_week": str(compare_monday) if compare_monday else None,
            "completeness": complete or {}, "warnings": report_metrics.get("warnings") or [],
            "compare_empty": compare_empty, "compare_unavailable_reason": compare_unavailable_reason,
            "summary_mode": is_summary_mode,
        }
        with _PLOT_LOCK:
            chart_files = self._plot(report_df, mapping, report_metrics, charts_dir, amount_mode, context)
        self._step(task, "plot_chart", "done", f"{len(chart_files)} 张图")

        fingerprint = snapshot.fingerprint
        facts = facts_mod.build_facts(report_metrics, mapping, str(report_monday) if report_monday else None, True, unit=unit, summary_mode=is_summary_mode)
        # P0-2/V7-4 仅当两周都确认完整且非 B 跨周才输出变化事实
        change_facts = []
        if compare_metrics and (complete or {}).get("report") and (complete or {}).get("compare") and not cross_week:
            change_facts = facts_mod.build_change_facts(report_metrics, compare_metrics, mapping)
        self._step(task, "facts", "done", f"{len(facts)} 张事实卡")

        summary, warning, summary_validation = self._summarize(report_metrics, facts, is_summary_mode, unit)
        context["summary_validation"] = summary_validation
        self._step(task, "write_summary", "done" if not warning else "done_with_warning", warning)
        self._step(task, "safety_check", "done" if not warning else "done_with_warning", warning or "通过")

        title = "销售数据汇总" if is_summary_mode else "销售数据周报"
        report_md = report_templates.render_report(
            report_metrics,
            summary,
            title=title,
            amount_mode=amount_mode,
            report_week=report_week,
            warnings=report_metrics.get("warnings") or [],
            product_ranking_available=report_metrics.get("product_ranking_available", True),
            channel_share_available=report_metrics.get("channel_share_available", True),
            unit=unit,
            summary_mode=is_summary_mode,
            context=context,
        )
        files.write_file(task_out / "report.md", report_md, config.output_dir, input_file=input_path, overwrite=overwrite)
        files.write_metrics_xlsx(report_metrics, task_out / "data_summary.xlsx", config.output_dir, context=context)

        basis = basis_mod.build_basis(
            field_mapping=mapping,
            amount_mode=amount_mode,
            report_week=report_week,
            compare_week=str(compare_monday) if compare_monday else None,
            completeness=complete or {},
            exclusions=[],
            metric_formula_version=METRIC_FORMULA_VERSION,
            verify_result={"passed": True, "report": True, "compare": compare_metrics is not None},
            source_fingerprint=fingerprint,
            unit=unit,
            compare_empty=compare_empty,
            compare_unavailable_reason=compare_unavailable_reason,
            context=context,
            confirmation=task.confirmation,
        )
        files.write_file(task_out / "analysis_basis.json", json.dumps(basis, ensure_ascii=False, indent=2), config.output_dir, overwrite=overwrite)
        self._step(task, "write_files", "done", str(task_out))

        deliverables = ["report.md", "data_summary.xlsx", "analysis_basis.json"] + [f"charts/{c.name}" for c in chart_files]
        changes = f"在 {task_out} 下生成报告、图表、汇总表与依据文件；按确认的数据版本生成，WorkMate 未修改原始文件 {input_path.name}；数字核对一致。"
        if warning:
            changes += f" 注意：{warning}"
        return {
            "task_id": task.task_id,
            "output_dir": str(task_out),
            "deliverables": deliverables,
            "changes": changes,
            "facts": facts,
            "change_facts": change_facts,
            "amount_mode": amount_mode,
            "report_week": report_week,
            "title": title,
            "summary_validation": summary_validation,
        }

    def _plot(self, report_df, mapping, metrics, charts_dir, amount_mode, context=None):
        from .tools.compute import _to_numeric_sales

        charts: list[Path] = []
        sales_numeric = _to_numeric_sales(report_df, mapping["sales"])
        daily = amounts.daily_trend(report_df, mapping, sales_numeric, amount_mode)
        if daily is not None and len(daily):
            p = charts_dir / "trend.png"
            plot.plot_trend_series(daily, p, context=context)
            charts.append(p)
        if metrics.get("product_ranking_available", True) and metrics.get("top5"):
            p = charts_dir / "top5.png"
            plot.plot_top5(metrics["top5"], p, context=context)
            charts.append(p)
        if metrics.get("channel_share_available", True) and metrics.get("channel_share"):
            p = charts_dir / "channel.png"
            plot.plot_channel(metrics["channel_share"], p, context=context)
            charts.append(p)
        return charts

    def _locate(self, file_path: str | None) -> Path:
        config = self.config
        if file_path:
            p = Path(file_path).expanduser()
            if not p.is_absolute():
                p = Path.cwd() / p
            if not p.exists():
                raise WorkmateError("FILE_NOT_FOUND", f"文件不存在：{p}")
            if not p.resolve().is_relative_to(config.data_dir.resolve()):
                raise WorkmateError("PERMISSION_DENIED", f"只能读取授权目录 {config.data_dir} 内的文件，请先把文件放进去。")
            return p
        matches = files.search_files("", config.data_dir)
        if not matches:
            raise WorkmateError("FILE_NOT_FOUND", "data 目录下没有找到 xlsx/csv，请先放入文件，或用 --file 指定。")
        return matches[0]

    def _summarize(self, metrics: dict, facts: list[dict], summary_mode: bool = False, unit: str = "单位待确认"):
        t0 = time.monotonic()
        metadata = {
            "provider": self.config.model_provider,
            "model": self.config.ollama_model if self.config.model_provider == "ollama" else "mock",
            "attempts": 0, "first_pass": False, "status": "fallback", "fallback_reason": None,
        }

        def finish(text, reason):
            metadata["elapsed_ms"] = round((time.monotonic() - t0) * 1000)
            metadata["fallback_reason"] = reason
            metadata["status"] = "fallback" if reason else "passed"
            return text, reason, metadata

        def fallback(reason):
            text = report_templates.conservative_summary(metrics, summary_mode, unit=unit)
            return finish(text + f"\n\n（自动降级：{reason}，请人工复核。）", reason)

        if self.provider is None:
            return fallback("模型初始化失败")
        model_facts = summary_mod.model_facts(facts)
        for attempt in range(3):
            metadata["attempts"] = attempt + 1
            try:
                raw = self.provider.complete(SUMMARY_SYSTEM, _facts_text(model_facts))
            except WorkmateError as exc:
                reason = "本地模型响应超时" if exc.code == "MODEL_TIMEOUT" else "模型不可用，请检查本地服务和配置"
                return fallback(reason)
            except Exception:
                return fallback("模型调用失败")
            try:
                text = summary_mod.validate_and_render(raw, model_facts, render_facts=facts)
            except (ValueError, TypeError, KeyError):
                self.storage.append_log(f"[task] 总结结构或事实校验未通过，尝试 {attempt + 1}/3")
                continue
            metadata["first_pass"] = attempt == 0
            return finish(text, None)
        return fallback("总结结构或事实校验未通过")

    def _step(self, task: Task, name: str, status: str, detail: str | None = None) -> None:
        task.steps.append(StepRecord(name=name, status=status, detail=detail, finished_at=now_iso()))
        task.updated_at = now_iso()
        self.storage.save_task(task)
        self.storage.append_trace({"ts": now_iso(), "task_id": task.task_id, "step": name, "status": status})
