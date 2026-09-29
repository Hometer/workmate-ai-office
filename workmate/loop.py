"""s01 Agent loop：编排 v0.6 主链路（检查/口径/周 → 计算 → 双周独立核对 → 事实 → 总结 → 落盘）。"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from uuid import uuid4

import pandas as pd

from . import basis as basis_mod
from . import facts as facts_mod
from . import inspect
from . import amounts
from . import weeks
from .config import Config
from .knowledge import report_templates
from .model import get_provider
from .schemas import StepRecord, Task, WorkmateError, now_iso
from .storage import Storage
from .tools import compute, files, plot, safety, verify

SUMMARY_SYSTEM = """你是 WorkMate 数据周报助手。根据给定的"已核对事实卡"写一段不超过 200 字的中文总结。
规则：
1. 只能用事实卡里的数字，绝不编造；没有依据不写建议、原因或预测。
2. 每个含数字的结论标注卡片编号（如 [total_sales]）。
3. 先结论后数据，短、有结论，不要空话套话。
4. 金额口径与周范围以事实卡为准，不得自行改口径。
输出：纯文本正文，不含任何标题。"""

METRIC_FORMULA_VERSION = "2026-09-29-v06-1"


def _facts_text(facts: list[dict]) -> str:
    return json.dumps(facts, ensure_ascii=False, indent=2)


class Loop:
    def __init__(self, config: Config):
        self.config = config
        self.storage = Storage(config.output_dir)
        self.provider = get_provider(config)

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
    ) -> dict:
        config = self.config
        config.ensure_dirs()
        if not (instruction and instruction.strip()):
            raise WorkmateError("BAD_INSTRUCTION", "请给一句任务指令，例如：把 sales.xlsx 做成销售周报。")
        if amount_mode not in ("A", "B"):
            raise WorkmateError("AMOUNT_MODE_REQUIRED", "请明确选择金额口径 A 或 B，不能默认。")

        task = Task(task_id=task_id or uuid4().hex[:12], instruction=instruction, input_file=file_path or "")
        task.status = "running"
        self.storage.save_task(task)
        self.storage.append_log(f"[task {task.task_id}] 开始")
        t0 = time.time()

        try:
            result = self._execute(task, file_path, overwrite, field_mapping, amount_mode, report_week, compare_week, complete, unit)
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

    def _execute(self, task, file_path, overwrite, field_mapping, amount_mode, report_week, compare_week, complete, unit):
        config = self.config

        input_path = self._locate(file_path)
        task.input_file = str(input_path)
        self._step(task, "search_files", "done", str(input_path))

        full_df = files.read_table(input_path)
        schema = files.describe_schema(full_df)
        self._step(task, "read_file", "done", f"shape={schema['shape']}")

        mapping = {k: v for k, v in (field_mapping or compute.infer_columns(full_df)).items() if v}
        if "sales" not in mapping:
            raise WorkmateError("COLUMN_UNKNOWN", "缺少销售额列，无法计算。")
        self._step(task, "infer_columns", "done", str(mapping))

        # G10 币种：多币种阻断
        currency_col, currency_distinct = inspect.detect_currency(full_df)
        if currency_distinct > 1:
            raise WorkmateError("MULTI_CURRENCY", f"币种列（{currency_col}）有 {currency_distinct} 种币种，不能混算。")

        # P0-1 全表销售额检查（报告/对比周之外的坏值也要阻断）
        compute._to_numeric_sales(full_df, mapping["sales"])

        report_monday = weeks.parse_monday(report_week)

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

        report_df = weeks.filter_to_week(full_df, mapping["date"], report_monday) if (report_monday and mapping.get("date")) else full_df
        if len(report_df) == 0:
            raise WorkmateError("REPORT_WEEK_EMPTY", "所选报告周没有记录，请选择有记录的报告周。")
        report_metrics = compute.compute_all(report_df, mapping, amount_mode)

        compare_metrics = None
        compare_empty = False
        if compare_monday and mapping.get("date"):
            compare_df = weeks.filter_to_week(full_df, mapping["date"], compare_monday)
            if len(compare_df) == 0:
                compare_empty = True
            else:
                compare_metrics = compute.compute_all(compare_df, mapping, amount_mode)

        # G8 B 模式跨任意自然周订单：归属不明确不出环比
        cross_week = False
        if amount_mode == "B" and mapping.get("date"):
            cross_week = self._b_multi_week(full_df, mapping)

        if report_metrics["mom_growth"] is None and compare_metrics is not None and (complete or {}).get("report") and (complete or {}).get("compare") and not cross_week:
            prev = compare_metrics["total_sales"]
            if prev and prev != 0:
                report_metrics["mom_growth"] = (report_metrics["total_sales"] - prev) / prev
        if cross_week:
            report_metrics.setdefault("warnings", []).append("部分订单跨报告周与对比周，环比暂不可用。")
        if compare_empty:
            report_metrics.setdefault("warnings", []).append("对比周无记录，无法比较。")
        self._step(task, "compute_metrics", "done", f"总销售额={report_metrics['total_sales']:,.2f}")

        # G9 独立核对：报告周 + 对比周都要通过
        issues = verify.verify_metrics(files.read_table(input_path), mapping, report_metrics, amount_mode, report_monday)
        if issues:
            self._step(task, "verify_metrics", "failed", json.dumps(issues, ensure_ascii=False))
            raise WorkmateError("VERIFY_FAILED", "数字核对不一致：" + json.dumps(issues, ensure_ascii=False))
        if compare_metrics is not None:
            c_issues = verify.verify_metrics(files.read_table(input_path), mapping, compare_metrics, amount_mode, compare_monday)
            if c_issues:
                self._step(task, "verify_metrics", "failed", json.dumps(c_issues, ensure_ascii=False))
                raise WorkmateError("VERIFY_FAILED", "对比周数字核对不一致：" + json.dumps(c_issues, ensure_ascii=False))
        self._step(task, "verify_metrics", "done", "数字核对一致（报告周+对比周）")

        # P0-8 有日期但未选报告周 → 汇总模式（无环比）
        has_date = bool(mapping.get("date"))
        is_summary_mode = (not has_date) or (has_date and report_monday is None)
        unit = inspect.currency_display_unit(full_df) or unit or "单位待确认"
        if is_summary_mode:
            report_metrics["mom_growth"] = None

        task_out = config.output_dir / task.task_id
        charts_dir = task_out / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)
        chart_files = self._plot(report_df, mapping, report_metrics, charts_dir, amount_mode)
        self._step(task, "plot_chart", "done", f"{len(chart_files)} 张图")

        fingerprint = inspect.file_fingerprint(input_path)
        facts = facts_mod.build_facts(report_metrics, mapping, str(report_monday) if report_monday else None, True, unit=unit, summary_mode=is_summary_mode)
        # P0-2/V7-4 仅当两周都确认完整且非 B 跨周才输出变化事实
        change_facts = []
        if compare_metrics and (complete or {}).get("report") and (complete or {}).get("compare") and not cross_week:
            change_facts = facts_mod.build_change_facts(report_metrics, compare_metrics, mapping)
        self._step(task, "facts", "done", f"{len(facts)} 张事实卡")

        summary, warning = self._summarize(report_metrics, facts, is_summary_mode)
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
        )
        files.write_file(task_out / "report.md", report_md, config.output_dir, input_file=input_path, overwrite=overwrite)
        files.write_metrics_xlsx(report_metrics, task_out / "data_summary.xlsx", config.output_dir)

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
        )
        files.write_file(task_out / "analysis_basis.json", json.dumps(basis, ensure_ascii=False, indent=2), config.output_dir, overwrite=overwrite)
        self._step(task, "write_files", "done", str(task_out))

        deliverables = ["report.md", "data_summary.xlsx", "analysis_basis.json"] + [f"charts/{c.name}" for c in chart_files]
        changes = f"在 {task_out} 下生成报告、图表、汇总表与依据文件；原始文件 {input_path.name} 未改动；数字核对一致。"
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
        }

    def _b_multi_week(self, full_df, mapping) -> bool:
        """B 模式：任一订单出现在多个自然周即归属不清（不限于报告/对比周）。"""
        order_col = mapping.get("order")
        if not order_col or not mapping.get("date"):
            return False
        d = pd.to_datetime(full_df[mapping["date"]], errors="coerce")
        ids = full_df[order_col].astype("string").str.strip()
        weeks_of: dict[str, set] = {}
        for oid, dv in zip(ids, d):
            if pd.isna(oid) or pd.isna(dv):
                continue
            s = str(oid).strip()
            if s == "":
                continue
            weeks_of.setdefault(s, set()).add(weeks.monday_of(pd.Timestamp(dv).date()))
        return any(len(s) > 1 for s in weeks_of.values())

    def _plot(self, report_df, mapping, metrics, charts_dir, amount_mode):
        from .tools.compute import _to_numeric_sales

        charts: list[Path] = []
        sales_numeric = _to_numeric_sales(report_df, mapping["sales"])
        daily = amounts.daily_trend(report_df, mapping, sales_numeric, amount_mode)
        if daily is not None and len(daily):
            p = charts_dir / "trend.png"
            plot.plot_trend_series(daily, p)
            charts.append(p)
        if metrics.get("product_ranking_available", True) and metrics.get("top5"):
            p = charts_dir / "top5.png"
            plot.plot_top5(metrics["top5"], p)
            charts.append(p)
        if metrics.get("channel_share_available", True) and metrics.get("channel_share"):
            p = charts_dir / "channel.png"
            plot.plot_channel(metrics["channel_share"], p)
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

    def _summarize(self, metrics: dict, facts: list[dict], summary_mode: bool = False) -> tuple[str, str | None]:
        for attempt in range(3):
            try:
                text = (self.provider.complete(SUMMARY_SYSTEM, _facts_text(facts)) or "").strip()
            except WorkmateError as e:
                return self._fallback_summary(metrics, f"模型不可用：{e.message}", summary_mode)
            if not text or len(text) > 200:
                continue
            check = safety.safety_check(text, metrics)
            if check["pass"]:
                has_digit = re.search(r"\d", text) is not None
                has_cite = re.search(r"\[[a-z_]+\]", text) is not None
                if has_digit and not has_cite:
                    if attempt < 2:
                        self.storage.append_log(f"[task] 总结含数字但未标注事实卡引用，重试 {attempt + 1}/3")
                        continue
                    return self._fallback_summary(metrics, "总结含数字但未标注事实卡引用", summary_mode)
                return text, None
            if attempt < 2:
                self.storage.append_log(f"[task] 总结审核未通过，重试 {attempt + 1}/3")
                continue
            return self._fallback_summary(metrics, "内容审核未通过", summary_mode)
        return self._fallback_summary(metrics, "总结生成未达要求", summary_mode)

    def _fallback_summary(self, metrics: dict, reason: str, summary_mode: bool = False) -> tuple[str, str]:
        text = report_templates.conservative_summary(metrics, summary_mode) + f"\n\n（自动降级：{reason}，请人工复核。）"
        return text, reason

    def _step(self, task: Task, name: str, status: str, detail: str | None = None) -> None:
        task.steps.append(StepRecord(name=name, status=status, detail=detail, finished_at=now_iso()))
        task.updated_at = now_iso()
        self.storage.save_task(task)
        self.storage.append_trace({"ts": now_iso(), "task_id": task.task_id, "step": name, "status": status})
