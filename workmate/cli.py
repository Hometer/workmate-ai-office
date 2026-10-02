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
    sub.add_parser("diagnose", help="检查本地模型与数据/成果目录，不读取业务内容")

    args = parser.parse_args(argv)
    if args.cmd == "diagnose":
        from .diagnostics import diagnose
        config = load_config()
        try:
            config.ensure_dirs()
            print(json.dumps(diagnose(config), ensure_ascii=False, indent=2))
            return 0
        except Exception:
            print(json.dumps({"error": {"code": "DIRECTORY_UNAVAILABLE", "message": "无法准备本地目录，请检查 .env 中的数据/成果目录及读写权限。"}}, ensure_ascii=False))
            return 1
    try:
        config = load_config()
        if args.cmd != "serve":
            loop = Loop(config)
            loop.storage.recover_interrupted()
        if args.cmd == "run":
            result = loop.run(args.instruction, args.file, overwrite=args.force, amount_mode=args.amount_mode)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.cmd == "serve":
            import uvicorn

            from .api import create_app

            app = create_app(config)
            print(f"WorkMate 已启动：http://{args.host}:{args.port}")
            uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
        else:
            task = loop.storage.load_task(args.task_id)
            if task is None:
                print(json.dumps({"error": {"code": "NOT_FOUND", "message": "任务不存在"}}, ensure_ascii=False, indent=2))
                return 1
            print(json.dumps(task.model_dump(), ensure_ascii=False, indent=2))
    except WorkmateError as e:
        print(json.dumps(e.to_dict(), ensure_ascii=False, indent=2))
        return 1
    except (OSError, ValueError):
        print(json.dumps({"error": {"code": "LOCAL_STATE_UNAVAILABLE", "message": "无法读取或写入本地状态，请先运行 workmate diagnose，检查数据/成果目录与状态文件；不要删除原表或旧成果。"}}, ensure_ascii=False))
        return 1
    return 0
