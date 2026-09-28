"""CLI 入口。"""
from __future__ import annotations

import argparse
import json

from .config import load_config
from .loop import Loop
from .schemas import WorkmateError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="workmate", description="WorkMate 销售数据周报（M1 骨架）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="跑一次周报任务")
    run_p.add_argument("--file", help="xlsx/csv 路径（可选，缺省搜 data 目录）")
    run_p.add_argument("--instruction", required=True, help="任务指令，如：把 sales.xlsx 做成销售周报")

    resume_p = sub.add_parser("resume", help="按任务 ID 查看任务状态/成果")
    resume_p.add_argument("--task-id", required=True)

    args = parser.parse_args(argv)
    loop = Loop(load_config())

    try:
        if args.cmd == "run":
            result = loop.run(args.instruction, args.file)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            task = loop.storage.load_task(args.task_id)
            if task is None:
                print(json.dumps({"error": {"code": "NOT_FOUND", "message": "任务不存在"}}, ensure_ascii=False, indent=2))
                return 1
            print(json.dumps(task.model_dump(), ensure_ascii=False, indent=2))
    except WorkmateError as e:
        print(json.dumps(e.to_dict(), ensure_ascii=False, indent=2))
        return 1
    return 0
