"""s01 Agent loop：编排主链路，接入 M2 的 verify_metrics / safety_check / 权限白名单 / 日志。"""
from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4

from .config import Config
from .knowledge import report_templates
from .model import get_provider
from .schemas import StepRecord, Task, WorkmateError, now_iso
from .storage import Storage
from .tools import compute, files, plot, safety, verify

SUMMARY_SYSTEM = """你是 WorkMate 数据周报助手，职责是：根据给定的真实指标数字，写一段 200 字左右的中文周报总结。
规则：
1. 只能用给定的数字，绝不编造；表里没有的指标写"本表无此数据"。
2. 先结论后数据，短、有结论，不要空话套话。
3. 数字保持原样，不要四舍五入到失真，也不要给约数。
4. 禁止自造百分比、趋势或同比/环比等表里没有的数据。
正例：本周总销售额 20,615.49 元，环比 -77.75%，Top5 商品为蓝牙耳机等，建议关注直播渠道。
反例（禁止）：总销售额大约两万元；同比上涨 30%。
输出：纯文本正文，不含任何标题。"""


def _metrics_text(metrics: dict) -> str:
    parts = [
        f"总销售额：{metrics['total_sales']:,.2f}",
        f"订单量：{metrics['order_count']}",
        f"客单价：{metrics['avg_order_value']:,.2f}" if metrics["avg_order_value"] is not None else "客单价：本表无此数据",
    ]
    mom = metrics.get("mom_growth")
    parts.append(f"环比增长率：{mom * 100:.2f}%" if mom is not None else "环比增长率：本表无此数据")
    top5 = metrics.get("top5") or []
    parts.append("Top5 商品：" + "、".join(f"{i['name']}({i['sales']:,.2f})" for i in top5) if top5 else "Top5 商品：本表无此数据")
    ch = metrics.get("channel_share") or []
    parts.append("渠道占比：" + "、".join(f"{i['name']}({i['share'] * 100:.1f}%)" for i in ch) if ch else "渠道占比：本表无此数据")
    return "\n".join(parts)


class Loop:
    def __init__(self, config: Config):
        self.config = config
        self.storage = Storage(config.output_dir)
        self.provider = get_provider(config)

    def run(self, instruction: str, file_path: str | None = None, overwrite: bool = False, task_id: str | None = None) -> dict:
        config = self.config
        config.ensure_dirs()
        if not (instruction and instruction.strip()):
            raise WorkmateError("BAD_INSTRUCTION", "请给一句任务指令，例如：把 sales.xlsx 做成销售周报。")

        task = Task(task_id=task_id or uuid4().hex[:12], instruction=instruction, input_file=file_path or "")
        task.status = "running"
        self.storage.save_task(task)
        self.storage.append_log(f"[task {task.task_id}] 开始，指令：{instruction}")
        t0 = time.time()

        try:
            result = self._execute(task, file_path, overwrite)
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
            task.updated_at = now_iso()
            self.storage.save_task(task)
            self.storage.append_log(f"[task {task.task_id}] 失败：{e.code}")
            raise

    def _execute(self, task: Task, file_path: str | None, overwrite: bool) -> dict:
        config = self.config

        # 1. search_files 定位（M2：只读授权目录）
        input_path = self._locate(file_path)
        task.input_file = str(input_path)
        self._step(task, "search_files", "done", str(input_path))

        # 2. read_file 读表
        df = files.read_table(input_path)
        schema = files.describe_schema(df)
        self._step(task, "read_file", "done", f"shape={schema['shape']}")

        # 3. 列名识别
        mapping = compute.infer_columns(df)
        self._step(task, "infer_columns", "done", str({k: str(v) for k, v in mapping.items()}))

        # 4. compute_metrics 本地算指标
        metrics = compute.compute_all(df, mapping)
        self._step(task, "compute_metrics", "done", f"总销售额={metrics['total_sales']:,.2f}")

        # 5. verify_metrics 重新读源文件独立重算核对（红线：不一致即失败）
        issues = verify.verify_metrics(files.read_table(input_path), mapping, metrics)
        if issues:
            self._step(task, "verify_metrics", "failed", json.dumps(issues, ensure_ascii=False))
            raise WorkmateError("VERIFY_FAILED", "数字核对不一致：" + json.dumps(issues, ensure_ascii=False))
        self._step(task, "verify_metrics", "done", "数字核对一致")

        # 6. plot_chart 本地画图
        task_out = config.output_dir / task.task_id
        charts_dir = task_out / "charts"
        chart_files = plot.plot_charts(df, mapping, metrics, charts_dir)
        self._step(task, "plot_chart", "done", f"{len(chart_files)} 张图")

        # 7. 写总结（模型）+ safety_check（审核；不过重试≤3 次，仍失败降级保守模板）
        summary, warning = self._summarize(metrics)
        self._step(task, "write_summary", "done" if not warning else "done_with_warning", warning)
        self._step(task, "safety_check", "done" if not warning else "done_with_warning", warning or "通过")

        # 8. write_file 落盘成品
        report_md = report_templates.render_report(metrics, summary)
        files.write_file(task_out / "report.md", report_md, config.output_dir, input_file=input_path, overwrite=overwrite)
        files.write_metrics_xlsx(metrics, task_out / "data_summary.xlsx", config.output_dir)
        self._step(task, "write_files", "done", str(task_out))

        deliverables = ["report.md", "data_summary.xlsx"] + [f"charts/{c.name}" for c in chart_files]
        changes = f"在 {task_out} 下生成报告、图表、汇总表；原始文件 {input_path.name} 未改动；数字核对一致。"
        if warning:
            changes += f" 注意：{warning}"
        return {"task_id": task.task_id, "output_dir": str(task_out), "deliverables": deliverables, "changes": changes}

    def _locate(self, file_path: str | None) -> Path:
        config = self.config
        if file_path:
            p = Path(file_path).expanduser()
            if not p.is_absolute():
                p = Path.cwd() / p
            if not p.exists():
                raise WorkmateError("FILE_NOT_FOUND", f"文件不存在：{p}")
            # M2 权限白名单：输入文件必须在授权目录内
            if not p.resolve().is_relative_to(config.data_dir.resolve()):
                raise WorkmateError("PERMISSION_DENIED", f"只能读取授权目录 {config.data_dir} 内的文件，请先把文件放进去。")
            return p
        matches = files.search_files("", config.data_dir)
        if not matches:
            raise WorkmateError("FILE_NOT_FOUND", "data 目录下没有找到 xlsx/csv，请先放入文件，或用 --file 指定。")
        return matches[0]

    def _summarize(self, metrics: dict) -> tuple[str, str | None]:
        for attempt in range(3):
            try:
                text = (self.provider.complete(SUMMARY_SYSTEM, _metrics_text(metrics)) or "").strip()
            except WorkmateError as e:
                return self._fallback_summary(metrics, f"模型不可用：{e.message}")
            if not text or len(text) > 800:
                continue
            check = safety.safety_check(text, metrics)
            if check["pass"]:
                return text, None
            if attempt < 2:
                self.storage.append_log(f"[task] 总结审核未通过，重试 {attempt + 1}/3：{'；'.join(check['reasons'])}")
                continue
            return self._fallback_summary(metrics, "内容审核未通过：" + "；".join(check["reasons"]))
        return self._fallback_summary(metrics, "总结生成未达要求")

    def _fallback_summary(self, metrics: dict, reason: str) -> tuple[str, str]:
        text = report_templates.conservative_summary(metrics) + f"\n\n（自动降级：{reason}，请人工复核。）"
        return text, reason

    def _step(self, task: Task, name: str, status: str, detail: str | None = None) -> None:
        task.steps.append(StepRecord(name=name, status=status, detail=detail, finished_at=now_iso()))
        task.updated_at = now_iso()
        self.storage.save_task(task)
        self.storage.append_trace({"ts": now_iso(), "task_id": task.task_id, "step": name, "status": status})
