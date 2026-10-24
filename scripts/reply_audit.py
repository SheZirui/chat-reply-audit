#!/usr/bin/env python3
"""CLI entry point. Run --help; ordinary analysis never calls an API."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from audit_core import (analyze, ensure_new_output, load_phases, parse_zone, prepare_review,
                        read_messages, review_template, write_analysis, write_json, write_review_report)


def main(argv=None):
    parser = argparse.ArgumentParser(description="双人聊天：时间戳筛候选 → 上下文审阅 → 证据报告")
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("analyze", help="本地统计，不输出正文、不联网")
    a.add_argument("--input", required=True); a.add_argument("--out", required=True)
    a.add_argument("--timezone", default="+08:00"); a.add_argument("--sender-a")
    a.add_argument("--phases"); a.add_argument("--as-of")
    a.add_argument("--short-minutes", type=float, default=120)
    a.add_argument("--thresholds", type=float, nargs="+", default=[120,180,240])
    a.add_argument("--candidate-minutes", type=float, default=240)
    p = sub.add_parser("prepare-review", help="显式提取私密上下文与审阅模板")
    p.add_argument("--input", required=True); p.add_argument("--analysis", required=True); p.add_argument("--out", required=True)
    p.add_argument("--sender-a"); p.add_argument("--include-content", action="store_true")
    p.add_argument("--before", type=int, default=8); p.add_argument("--after", type=int, default=10)
    p.add_argument("--max-message-chars", type=int, default=1200)
    p.add_argument("--events", nargs="+", help="仅提取指定候选编号，如 E000007 E000030")
    wb = sub.add_parser("review-workbench", help="生成本机浏览器可填写的离线复核表单")
    wb.add_argument("--packet", required=True); wb.add_argument("--out", required=True)
    wb.add_argument("--reviews", help="可选：预填已有结果；保留原始审阅来源")
    r = sub.add_parser("apply-review", help="校验证据并生成含原文复核报告")
    r.add_argument("--packet", required=True); r.add_argument("--reviews", required=True); r.add_argument("--out", required=True)
    r.add_argument("--allow-partial", action="store_true")
    api = sub.add_parser("review-api", help="可选：显式发送候选上下文到兼容API")
    api.add_argument("--packet", required=True); api.add_argument("--out")
    api.add_argument("--endpoint", default=os.getenv("CHAT_REVIEW_API_URL"))
    api.add_argument("--model", default=os.getenv("CHAT_REVIEW_MODEL"))
    api.add_argument("--dry-run", action="store_true"); api.add_argument("--send-content", action="store_true")
    api.add_argument("--allow-local-endpoint", action="store_true")
    api.add_argument("--max-cases", type=int); api.add_argument("--attempts", type=int, default=1)
    api.add_argument("--timeout", type=float, default=60); api.add_argument("--max-case-chars", type=int, default=60000)
    api.add_argument("--max-output-tokens", type=int, default=1800); api.add_argument("--no-json-mode", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "analyze":
            zone = parse_zone(args.timezone)
            messages, audit = read_messages(args.input, zone, args.sender_a)
            result = analyze(messages, audit, args.timezone, load_phases(args.phases, zone), args.as_of,
                             args.short_minutes, args.thresholds, args.candidate_minutes)
            write_analysis(args.out, result)
            print(f"统计完成：{len(messages)}条有效消息，{len(result['candidates'])}个候选。未输出正文，未调用API。")
        elif args.command == "prepare-review":
            if not args.include_content:
                raise ValueError("此步骤会导出正文片段；确认需要后显式加 --include-content")
            result = json.loads(Path(args.analysis).read_text(encoding="utf-8-sig"))
            messages, audit = read_messages(args.input, parse_zone(result["config"]["timezone"]), args.sender_a, content=True)
            packet = prepare_review(messages, audit, result, args.before, args.after, args.max_message_chars)
            from review_workbench import select_cases
            packet = select_cases(packet, args.events)
            out = ensure_new_output(args.out)
            write_json(out / "context_packet.json", packet)
            write_json(out / "reviews_template.json", review_template(packet))
            print(f"已准备{len(packet['cases'])}个候选的私密上下文；未调用API。")
        elif args.command == "review-workbench":
            from review_workbench import write_workbench
            packet = json.loads(Path(args.packet).read_text(encoding="utf-8-sig"))
            reviews = json.loads(Path(args.reviews).read_text(encoding="utf-8-sig")) if args.reviews else None
            write_workbench(args.out, packet, reviews)
            print("离线复核表单已生成：index.html。含正文，请私密保存；未联网，未调用API。")
        elif args.command == "apply-review":
            packet = json.loads(Path(args.packet).read_text(encoding="utf-8-sig"))
            reviews = json.loads(Path(args.reviews).read_text(encoding="utf-8-sig"))
            write_review_report(args.out, packet, reviews, args.allow_partial)
            print("复核报告已生成；模型建议会明确标记为尚未人工确认。")
        else:
            from llm_review import preview, review_api
            packet = json.loads(Path(args.packet).read_text(encoding="utf-8-sig"))
            print(json.dumps(preview(packet, args.max_cases), ensure_ascii=False, indent=2))
            if args.dry_run:
                return 0
            if not args.endpoint or not args.model or not args.out:
                raise ValueError("实际调用需要 endpoint、model、out；密钥从CHAT_REVIEW_API_KEY读取")
            out = Path(args.out)
            if out.exists():
                raise ValueError("API输出文件已存在；请选择新文件")
            result = review_api(packet, args.endpoint, args.model, os.getenv("CHAT_REVIEW_API_KEY"), args.max_cases,
                                args.attempts, args.timeout, args.max_case_chars, not args.no_json_mode,
                                args.max_output_tokens, args.allow_local_endpoint, args.send_content)
            out.parent.mkdir(parents=True, exist_ok=True)
            write_json(out, result)
            print("模型建议已保存；请人工核对后使用，未自动标记为人工结论。")
        return 0
    except (ValueError, KeyError, TypeError) as exc:
        # Only our deliberate ValueError messages are shown; do not print source rows or API bodies.
        if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError):
            print("未完成：" + str(exc))
        else:
            print("未完成：输入文件结构或JSON格式不符合文档。")
        return 2
    except OSError:
        print("未完成：文件无法读写，请检查路径和权限。")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
