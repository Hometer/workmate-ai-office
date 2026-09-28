"""s01 Agent loop：编排 v0.5 主链路（检查/口径/周 → 计算 → 独立核对 → 事实 → 总结 → 落盘）。"""
from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4

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

METRIC_FORMULA_VERSION = "2026-09-28-v05-1"


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
        amount_mode: str = "A",
        report_week: str | None = None,
        compare_week: str | None = None,
        complete: dict | None = None,
    ) -> dict:
        config = self.config
        config.ensure_dirs()
        if not (instruction and instruction.strip()):
            raise WorkmateError("BAD_INSTRUCTION", "请给一句任务指令，例如：把 sales.xlsx 做成销售周报。")

        task = Task(task_id=task_id or uuid4().hex[:12], instruction=instruction, input_file=file_path or "")
        task.status = "running"
        self.storage.save_task(task)
        self.storage.append_log(f"[task {task.task_id}] 开始")
        t0 = time.time()

        try:
            result = self._execute(task, file_path, overwrite, field_mapping, amount_mode, report_week, compare_week, complete)
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

    def _execute(self, task, file_path, overwrite, field_mapping, amount_mode, report_week, compare_week, complete):
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

        report_monday = weeks.parse_monday(report_week)
        compare_monday = weeks.parse_monday(compare_week)

        # 主指标（报告周）；无日期或未选周 → 全表
        report_df = weeks.filter_to_week(full_df, mapping["date"], report_monday) if (report_monday and mapping.get("date")) else full_df
        report_metrics = compute.compute_all(report_df, mapping, amount_mode)
        compare_metrics = None
        if compare_monday and mapping.get("date"):
            compare_df = weeks.filter_to_week(full_df, mapping["date"], compare_monday)
            compare_metrics = compute.compute_all(compare_df, mapping, amount_mode)

        # 环比：跨两周，需用户分别确认完整
        if report_metrics["mom_growth"] is None and compare_metrics is not None and (complete or {}).get("report") and (complete or {}).get("compare"):
            prev = compare_metrics["total_sales"]
            if prev and prev != 0:
                report_metrics["mom_growth"] = (report_metrics["total_sales"] - prev) / prev
        self._step(task, "compute_metrics", "done", f"总销售额={report_metrics['total_sales']:,.2f}")

        # 独立核对（报告周核心指标）
        issues = verify.verify_metrics(files.read_table(input_path), mapping, report_metrics, amount_mode, report_monday)
        if issues:
            self._step(task, "verify_metrics", "failed", json.dumps(issues, ensure_ascii=False))
            raise WorkmateError("VERIFY_FAILED", "数字核对不一致：" + json.dumps(issues, ensure_ascii=False))
        self._step(task, "verify_metrics", "done", "数字核对一致")

        # 画图
        task_out = config.output_dir / task.task_id
        charts_dir = task_out / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)
        chart_files = self._plot(report_df, mapping, report_metrics, charts_dir, amount_mode)
        self._step(task, "plot_chart", "done", f"{len(chart_files)} 张图")

        # 事实卡与变化事实
        fingerprint = inspect.file_fingerprint(input_path)
        facts = facts_mod.build_facts(report_metrics, mapping, str(report_monday) if report_monday else None, True)
        change_facts = facts_mod.build_change_facts(report_metrics, compare_metrics or {}, mapping) if compare_metrics else []
        self._step(task, "facts", "done", f"{len(facts)} 张事实卡")

        # 总结（模型，基于事实卡）
        summary, warning = self._summarize(report_metrics, facts)
        self._step(task, "write_summary", "done" if not warning else "done_with_warning", warning)
        self._step(task, "safety_check", "done" if not warning else "done_with_warning", warning or "通过")

        # 落盘
        is_summary_mode = not mapping.get("date")
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
        )
        files.write_file(task_out / "report.md", report_md, config.output_dir, input_file=input_path, overwrite=overwrite)
        files.write_metrics_xlsx(report_metrics, task_out / "data_summary.xlsx", config.output_dir)

        basis = basis_mod.build_basis(
            field_mapping=mapping,
            amount_mode=amount_mode,
            report_week=report_week,
            compare_week=compare_week,
            completeness=complete or {},
            exclusions=[],
            metric_formula_version=METRIC_FORMULA_VERSION,
            verify_result={"passed": True},
            source_fingerprint=fingerprint,
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

    def _plot(self, report_df, mapping, metrics, charts_dir, amount_mode):
        charts: list[Path] = []
        sales_numeric = None
        # 重新算一遍数值用于趋势（保持与 compute 一致）
        from .tools.compute import _to_numeric_sales

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

    def _summarize(self, metrics: dict, facts: list[dict]) -> tuple[str, str | None]:
        for attempt in range(3):
            try:
                text = (self.provider.complete(SUMMARY_SYSTEM, _facts_text(facts)) or "").strip()
            except WorkmateError as e:
                return self._fallback_summary(metrics, f"模型不可用：{e.message}")
            if not text or len(text) > 800:
                continue
            check = safety.safety_check(text, metrics)
            if check["pass"]:
                return text, None
            if attempt < 2:
                self.storage.append_log(f"[task] 总结审核未通过，重试 {attempt + 1}/3")
                continue
            return self._fallback_summary(metrics, "内容审核未通过")
        return self._fallback_summary(metrics, "总结生成未达要求")

    def _fallback_summary(self, metrics: dict, reason: str) -> tuple[str, str]:
        text = report_templates.conservative_summary(metrics) + f"\n\n（自动降级：{reason}，请人工复核。）"
        return text, reason

    def _step(self, task: Task, name: str, status: str, detail: str | None = None) -> None:
        task.steps.append(StepRecord(name=name, status=status, detail=detail, finished_at=now_iso()))
        task.updated_at = now_iso()
        self.storage.save_task(task)
        self.storage.append_trace({"ts": now_iso(), "task_id": task.task_id, "step": name, "status": status})
