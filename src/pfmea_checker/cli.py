"""Command line interface for pfmea-checker.

Exit codes:
  0  no validation errors (high-RPN / high-severity flags are warnings)
  2  validation errors found in the worksheet
  1  file or usage error (missing file, unreadable CSV, bad arguments)
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .core import (
    DEFAULT_THRESHOLD,
    HIGH_SEVERITY,
    Analysis,
    analyze,
    render_report,
    write_demo,
)


class UsageError(Exception):
    """Raised in place of argparse's default SystemExit(2) so that usage
    errors map to exit code 1 (2 is reserved for validation errors)."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # noqa: D102 - argparse hook
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="pfmea-check",
        description="PFMEA 工作表校验与 RPN/帕累托分析 / PFMEA worksheet checker (RPN + Pareto)",
    )
    p.add_argument("file", nargs="?", help="PFMEA 导出的 CSV 文件路径")
    p.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
        metavar="N",
        help="RPN 标记阈值（默认 %d）" % DEFAULT_THRESHOLD,
    )
    p.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p.add_argument(
        "--report",
        metavar="FILE.md",
        help="把 Markdown 评审摘要写入指定文件",
    )
    p.add_argument(
        "--demo",
        metavar="PATH",
        help="生成示例 PFMEA CSV 到 PATH（含故意设置的错误行，便于演示校验）",
    )
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    return p


def _fmt_row_short(a: Analysis, r) -> str:
    return "  第 %d 行  RPN %s  S=%s O=%s D=%s  %s" % (
        r.number,
        r.rpn if r.rpn is not None else "-",
        r.severity if r.severity is not None else "-",
        r.occurrence if r.occurrence is not None else "-",
        r.detection if r.detection is not None else "-",
        r.failure_mode,
    )


def print_summary(a: Analysis) -> None:
    print("PFMEA 检查：%s" % a.source)
    print(
        "数据行 %d（可计算 RPN %d），校验问题 %d 个"
        % (a.data_row_count, len(a.valid_rows), len(a.issues))
    )
    if a.issues:
        print("\n校验问题 / Validation issues:")
        for issue in a.issues:
            print("  第 %d 行 [%s] %s" % (issue.row, issue.field, issue.message))
    if a.high_severity_rows:
        print("\n高严重度行（S ≥ %d，不看 RPN）：" % HIGH_SEVERITY)
        for r in a.high_severity_rows:
            print(_fmt_row_short(a, r))
    if a.high_rpn_rows:
        print("\n高 RPN 行（RPN ≥ %d）：" % a.threshold)
        for r in a.high_rpn_rows:
            print(_fmt_row_short(a, r))
    if a.top_rpn_rows:
        print("\nRPN 最高的行 / Top RPN rows:")
        for r in a.top_rpn_rows:
            print(_fmt_row_short(a, r))
    if a.pareto:
        print("\n帕累托（按 RPN 份额）/ Pareto:")
        for entry in a.pareto:
            print(
                "  %-16s 行数 %d  RPN 合计 %d  份额 %.1f%%  累计 %.1f%%"
                % (
                    entry["failure_mode"],
                    entry["rows"],
                    entry["rpn_total"],
                    entry["share_pct"],
                    entry["cumulative_pct"],
                )
            )
    print("\n注：本工具仅辅助人工评审，不代替工程师批准 PFMEA。")


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except UsageError as exc:
        print("pfmea-check: %s" % exc, file=sys.stderr)
        print("用法见 pfmea-check --help", file=sys.stderr)
        return 1

    if args.demo:
        try:
            write_demo(args.demo)
        except OSError as exc:
            print("pfmea-check: 无法写入示例文件：%s" % exc, file=sys.stderr)
            return 1
        print("示例文件已生成：%s" % args.demo)
        print("试着运行：pfmea-check %s" % args.demo)
        if not args.file:
            return 0

    if not args.file:
        print("pfmea-check: 缺少 CSV 文件参数（或用 --demo 生成示例）", file=sys.stderr)
        return 1

    if args.threshold < 1:
        print("pfmea-check: --threshold 必须 ≥ 1", file=sys.stderr)
        return 1

    try:
        analysis = analyze(Path(args.file), threshold=args.threshold)
    except FileNotFoundError:
        print("pfmea-check: 文件不存在：%s" % args.file, file=sys.stderr)
        return 1
    except (IsADirectoryError, PermissionError, UnicodeDecodeError, csv.Error, ValueError) as exc:
        print("pfmea-check: 无法读取文件：%s" % exc, file=sys.stderr)
        return 1

    if args.report:
        try:
            Path(args.report).write_text(render_report(analysis), encoding="utf-8")
        except OSError as exc:
            print("pfmea-check: 无法写入报告：%s" % exc, file=sys.stderr)
            return 1
        print("报告已写入：%s" % args.report)

    if args.json:
        print(json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2))
    else:
        print_summary(analysis)

    return 2 if analysis.issues else 0


if __name__ == "__main__":
    sys.exit(main())
