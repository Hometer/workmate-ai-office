"""s01 Agent loop：编排"读表 → 算指标 → 画图 → 写总结 → 落盘"主链路。"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .config import Config
from .knowledge import report_templates
from .model import get_provider
from .schemas import StepRecord, Task, WorkmateError, now_iso
from .storage import Storage
from .tools import compute, files, plot

SUMMARY_SYSTEM = """你是 WorkMate 数据周报助手，职责是：根据给定的真实指标数字，写一段 200 字左右的中文周报总结。
规则：
1. 只能用给定的数字，绝不编造；表里没有的指标写"本表无此数据"。
2. 先结论后数据，短、有结论，不要空话套话。
3. 数字保持原样，不要四舍五入到失真。
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

    def run(self, instruction: str, file_path: str | None = None) -> dict:
        config = self.config
        config.ensure_dirs()
        if not (instruction and instruction.strip()):
            raise WorkmateError("BAD_INSTRUCTION", "请给一句任务指令，例如：把 sales.xlsx 做成销售周报。")

        task = Task(task_id=uuid4().hex[:12], instruction=instruction, input_file=file_path or "")
        task.status = "running"
        self.storage.save_task(task)

        try:
            result = self._execute(task, file_path)
            task.status = "done"
            task.result = result
            task.updated_at = now_iso()
            self.storage.save_task(task)
            return result
        except WorkmateError:
            task.status = "failed"
            task.updated_at = now_iso()
            self.storage.save_task(task)
            raise

    def _execute(self, task: Task, file_path: str | None) -> dict:
        config = self.config

        # 1. search_files 定位输入文件
        input_path = self._locate(file_path)
        task.input_file = str(input_path)
        self._step(task, "search_files", "done", str(input_path))

        # 2. read_file 读表（不整表进上下文，M1 只在本地内存处理）
        df = files.read_table(input_path)
        schema = files.describe_schema(df)
        self._step(task, "read_file", "done", f"shape={schema['shape']}")

        # 3. 列名识别
        mapping = compute.infer_columns(df)
        self._step(task, "infer_columns", "done", str({k: str(v) for k, v in mapping.items()}))

        # 4. compute_metrics 本地算指标
        metrics = compute.compute_all(df, mapping)
        self._step(task, "compute_metrics", "done", f"总销售额={metrics['total_sales']:,.2f}")

        # 5. plot_chart 本地画图
        task_out = config.output_dir / task.task_id
        charts_dir = task_out / "charts"
        chart_files = plot.plot_charts(df, mapping, metrics, charts_dir)
        self._step(task, "plot_chart", "done", f"{len(chart_files)} 张图")

        # 6. 写总结（模型；失败则降级，不假装成功）
        summary, warning = self._summarize(metrics)
        self._step(task, "write_summary", "done" if not warning else "done_with_warning", warning)

        # 7. write_file 落盘成品
        report_md = report_templates.render_report(metrics, summary)
        files.write_file(task_out / "report.md", report_md, config.output_dir, input_file=input_path)
        files.write_metrics_xlsx(metrics, task_out / "data_summary.xlsx", config.output_dir)
        self._step(task, "write_files", "done", str(task_out))

        deliverables = ["report.md", "data_summary.xlsx"] + [f"charts/{c.name}" for c in chart_files]
        changes = f"在 {task_out} 下生成报告、图表、汇总表；原始文件 {input_path.name} 未改动。"
        if warning:
            changes += f" 注意：{warning}"
        return {"task_id": task.task_id, "output_dir": str(task_out), "deliverables": deliverables, "changes": changes}

    def _locate(self, file_path: str | None) -> Path:
        if file_path:
            p = Path(file_path).expanduser()
            if not p.is_absolute():
                p = Path.cwd() / p
            if not p.exists():
                raise WorkmateError("FILE_NOT_FOUND", f"文件不存在：{p}")
            return p
        matches = files.search_files("", self.config.data_dir)
        if not matches:
            raise WorkmateError("FILE_NOT_FOUND", "data 目录下没有找到 xlsx/csv，请先放入文件，或用 --file 指定。")
        return matches[0]

    def _summarize(self, metrics: dict) -> tuple[str, str | None]:
        try:
            text = self.provider.complete(SUMMARY_SYSTEM, _metrics_text(metrics))
            text = (text or "").strip()
            if not text or len(text) > 800:
                raise WorkmateError("SUMMARY_INVALID", "总结为空或过长")
            return text, None
        except WorkmateError as e:
            return f"（总结未能生成：{e.message}。关键数字与图表已就绪。）", e.message

    def _step(self, task: Task, name: str, status: str, detail: str | None = None) -> None:
        task.steps.append(StepRecord(name=name, status=status, detail=detail, finished_at=now_iso()))
        task.updated_at = now_iso()
        self.storage.save_task(task)
        self.storage.append_trace({"ts": now_iso(), "task_id": task.task_id, "step": name, "status": status})
