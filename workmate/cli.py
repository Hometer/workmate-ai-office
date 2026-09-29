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
    run_p.add_argument("--amount-mode", required=True, choices=["A", "B"], help="金额口径：A 每行金额 / B 整单金额去重")
    run_p.add_argument("--force", action="store_true", help="允许覆盖已有成品文件（原始数据文件永不覆盖）")

    resume_p = sub.add_parser("resume", help="按任务 ID 查看任务状态/成果")
    resume_p.add_argument("--task-id", required=True)

    serve_p = sub.add_parser("serve", help="启动本地网页界面")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    loop = Loop(load_config())
    loop.storage.recover_interrupted()

    try:
        if args.cmd == "run":
            result = loop.run(args.instruction, args.file, overwrite=args.force, amount_mode=args.amount_mode)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.cmd == "serve":
            import uvicorn

            from .api import create_app

            print(f"WorkMate 已启动：http://{args.host}:{args.port}")
            uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
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
