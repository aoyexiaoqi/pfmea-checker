"""Core analysis for pfmea-checker.

Reads a PFMEA worksheet exported as CSV, validates its structure, computes
RPN (Risk Priority Number = Severity x Occurrence x Detection) for every row
whose ratings are usable, flags high-RPN and high-severity rows, and builds a
Pareto ranking of failure modes by RPN share.

Scope note: v1 covers RPN and structural checks only. AIAG-VDA Action
Priority (AP) lookup is deliberately NOT implemented.

This module assists human review; nothing here approves a PFMEA.
"""

import csv
from dataclasses import dataclass, field as _dc_field
from pathlib import Path
from typing import Dict, List, Optional, Union

# Exact CSV header names (column order in the file does not matter).
COLUMNS = [
    "process_step",
    "failure_mode",
    "failure_effect",
    "severity",
    "failure_cause",
    "occurrence",
    "prevention_control",
    "detection_control",
    "detection",
]

# Text fields that must be non-empty for a row to be considered complete.
REQUIRED_TEXT_FIELDS = [
    "failure_mode",
    "failure_effect",
    "failure_cause",
    "prevention_control",
    "detection_control",
]

# Rating fields; each must be an integer in [1, 10].
RATING_FIELDS = ["severity", "occurrence", "detection"]

DEFAULT_THRESHOLD = 100
HIGH_SEVERITY = 9
TOP_RPN_LIMIT = 10


@dataclass
class Issue:
    """One validation problem, tied to a CSV row number (header = row 1)."""

    row: int
    field: str
    message: str

    def to_dict(self) -> Dict[str, object]:
        return {"row": self.row, "field": self.field, "message": self.message}


@dataclass
class Row:
    """One data row of the worksheet."""

    number: int  # CSV row number; the first data row is 2
    process_step: str = ""
    failure_mode: str = ""
    failure_effect: str = ""
    failure_cause: str = ""
    prevention_control: str = ""
    detection_control: str = ""
    severity: Optional[int] = None
    occurrence: Optional[int] = None
    detection: Optional[int] = None
    rpn: Optional[int] = None  # None when any rating is missing/invalid

    def to_dict(self) -> Dict[str, object]:
        return {
            "row": self.number,
            "process_step": self.process_step,
            "failure_mode": self.failure_mode,
            "failure_effect": self.failure_effect,
            "severity": self.severity,
            "failure_cause": self.failure_cause,
            "occurrence": self.occurrence,
            "prevention_control": self.prevention_control,
            "detection_control": self.detection_control,
            "detection": self.detection,
            "rpn": self.rpn,
        }


@dataclass
class Analysis:
    """Full result of checking one CSV file."""

    source: str
    threshold: int
    rows: List[Row] = _dc_field(default_factory=list)
    issues: List[Issue] = _dc_field(default_factory=list)

    @property
    def data_row_count(self) -> int:
        return len(self.rows)

    @property
    def valid_rows(self) -> List[Row]:
        """Rows whose RPN could be computed (all three ratings usable)."""
        return [r for r in self.rows if r.rpn is not None]

    @property
    def high_rpn_rows(self) -> List[Row]:
        """Rows with RPN >= threshold, highest RPN first."""
        flagged = [r for r in self.valid_rows if r.rpn >= self.threshold]
        return sorted(flagged, key=lambda r: (-r.rpn, r.number))

    @property
    def high_severity_rows(self) -> List[Row]:
        """Rows with severity >= 9, regardless of RPN (row order kept)."""
        return [
            r
            for r in self.rows
            if r.severity is not None and r.severity >= HIGH_SEVERITY
        ]

    @property
    def top_rpn_rows(self) -> List[Row]:
        """Up to TOP_RPN_LIMIT rows with the highest RPN."""
        ordered = sorted(self.valid_rows, key=lambda r: (-r.rpn, r.number))
        return ordered[:TOP_RPN_LIMIT]

    @property
    def pareto(self) -> List[Dict[str, object]]:
        """Failure modes ranked by total RPN share, with cumulative %.

        Percentages are computed on the raw totals and rounded to one
        decimal for display; the last cumulative value is exactly 100.0
        whenever at least one valid row exists.
        """
        totals: Dict[str, Dict[str, int]] = {}
        for r in self.valid_rows:
            entry = totals.setdefault(r.failure_mode, {"rows": 0, "rpn_total": 0})
            entry["rows"] += 1
            entry["rpn_total"] += r.rpn
        grand = sum(e["rpn_total"] for e in totals.values())
        result: List[Dict[str, object]] = []
        if grand <= 0:
            return result
        cumulative = 0
        for mode, entry in sorted(
            totals.items(), key=lambda kv: (-kv[1]["rpn_total"], kv[0])
        ):
            cumulative += entry["rpn_total"]
            result.append(
                {
                    "failure_mode": mode,
                    "rows": entry["rows"],
                    "rpn_total": entry["rpn_total"],
                    "share_pct": round(entry["rpn_total"] / grand * 100, 1),
                    "cumulative_pct": round(cumulative / grand * 100, 1),
                }
            )
        return result

    def to_dict(self) -> Dict[str, object]:
        return {
            "file": self.source,
            "threshold": self.threshold,
            "row_count": self.data_row_count,
            "valid_rpn_rows": len(self.valid_rows),
            "issue_count": len(self.issues),
            "issues": [i.to_dict() for i in self.issues],
            "high_rpn_rows": [r.to_dict() for r in self.high_rpn_rows],
            "high_severity_rows": [r.to_dict() for r in self.high_severity_rows],
            "top_rpn": [r.to_dict() for r in self.top_rpn_rows],
            "pareto": self.pareto,
        }


def _clean(value: object) -> str:
    """Normalize a raw CSV cell to a stripped string (None -> '')."""
    if value is None:
        return ""
    return str(value).strip()


def _parse_rating(
    raw: str, field_name: str, row_number: int, issues: List[Issue]
) -> Optional[int]:
    """Parse one S/O/D cell; append an Issue and return None when unusable."""
    if raw == "":
        issues.append(Issue(row_number, field_name, "%s 为空（必填，须为 1–10 的整数）" % field_name))
        return None
    try:
        value = int(raw)
    except ValueError:
        issues.append(
            Issue(row_number, field_name, "%s 不是整数：%r" % (field_name, raw))
        )
        return None
    if not 1 <= value <= 10:
        issues.append(
            Issue(
                row_number,
                field_name,
                "%s 超出范围 1–10：%d" % (field_name, value),
            )
        )
        return None
    return value


def analyze(path: Union[str, Path], threshold: int = DEFAULT_THRESHOLD) -> Analysis:
    """Check the PFMEA CSV at *path* and return an Analysis.

    Raises FileNotFoundError / IsADirectoryError / UnicodeDecodeError /
    csv.Error / ValueError("empty file") for unreadable input; the CLI maps
    those to exit code 1. Structural problems inside the file are reported
    as Issue entries instead of exceptions.
    """
    path = Path(path)
    analysis = Analysis(source=str(path), threshold=threshold)
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError("empty file: no header row")
        headers = [(_clean(h)) for h in reader.fieldnames]
        reader.fieldnames = headers
        missing_columns = [c for c in COLUMNS if c not in headers]
        for col in missing_columns:
            analysis.issues.append(
                Issue(1, col, "缺少必需的列：%s" % col)
            )
        for raw_row in reader:
            row_number = reader.line_num
            values = {col: _clean(raw_row.get(col)) for col in COLUMNS}
            row = Row(
                number=row_number,
                process_step=values["process_step"],
                failure_mode=values["failure_mode"],
                failure_effect=values["failure_effect"],
                failure_cause=values["failure_cause"],
                prevention_control=values["prevention_control"],
                detection_control=values["detection_control"],
            )
            for name in REQUIRED_TEXT_FIELDS:
                if values[name] == "":
                    analysis.issues.append(
                        Issue(row_number, name, "%s 为空（必填项）" % name)
                    )
            ratings = {}
            for name in RATING_FIELDS:
                ratings[name] = _parse_rating(
                    values[name], name, row_number, analysis.issues
                )
            row.severity = ratings["severity"]
            row.occurrence = ratings["occurrence"]
            row.detection = ratings["detection"]
            if None not in (row.severity, row.occurrence, row.detection):
                row.rpn = row.severity * row.occurrence * row.detection
            analysis.rows.append(row)
    return analysis


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

DEMO_ROWS = [
    ["电阻点焊", "焊点虚焊", "焊接强度不足，零件在振动中脱落", "8", "电极帽磨损导致电流密度下降", "6", "电极帽定周期修磨并点检", "焊接电流/电压实时监控", "7"],
    ["电阻点焊", "焊点烧穿", "板材破损，工件报废", "7", "焊接电流设定过大", "3", "参数点检表逐班确认", "首件目视检查焊点外观", "5"],
    ["注塑成型", "外壳缩水", "外观不良，客户投诉", "5", "保压压力不足", "5", "首件确认保压参数", "外观全检", "4"],
    ["螺丝锁付", "螺丝漏锁", "组件松动，整机功能失效", "9", "操作员漏作业", "2", "防错计数器，漏锁报警", "电批扭矩数据自动记录", "3"],
    ["插件", "电容极性反插", "通电烧毁电路板", "9", "物料极性标识不清", "3", "来料检验核对极性标识", "AOI 自动光学检测", "2"],
    ["涂胶", "胶量不足", "密封失效，产品进水", "6", "胶阀堵塞", "4", "点胶机压力点检", "", "6"],
    ["压装", "压装不到位", "轴承异响，寿命下降", "7", "压机行程设定错误", "3", "位移-压力曲线监控", "终检扭力抽测", "4"],
    ["贴标", "标签贴错型号", "错货出货，客户投诉", "6", "标签与工单不符", "4", "扫码校验工单与标签", "出货抽检", "abc"],
]


def write_demo(path: Union[str, Path]) -> Path:
    """Write the demo PFMEA CSV (8 rows: one missing-field, one bad rating)."""
    path = Path(path)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        writer.writerows(DEMO_ROWS)
    return path


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

DISCLAIMER = (
    "本报告由 pfmea-checker 自动生成，仅辅助人工评审；"
    "PFMEA 的批准须由负责工程师完成，本工具不代替工程师批准。\n"
    "Generated by pfmea-checker to assist human review only; "
    "this tool does not approve a PFMEA on behalf of an engineer."
)


def _row_line(r: Row) -> str:
    return "| %d | %s | %s | %s | %s | %s |" % (
        r.number,
        r.failure_mode,
        r.severity if r.severity is not None else "-",
        r.occurrence if r.occurrence is not None else "-",
        r.detection if r.detection is not None else "-",
        r.rpn if r.rpn is not None else "-",
    )


def render_report(analysis: Analysis) -> str:
    """Render a Markdown review summary for *analysis*."""
    a = analysis
    lines = []
    lines.append("# PFMEA 检查报告 / PFMEA Check Report")
    lines.append("")
    lines.append("- 源文件 / Source: `%s`" % a.source)
    lines.append("- RPN 阈值 / Threshold: %d" % a.threshold)
    lines.append("")
    lines.append("## 概览 / Overview")
    lines.append("")
    lines.append("| 项目 | 数量 |")
    lines.append("| --- | --- |")
    lines.append("| 数据行 / Data rows | %d |" % a.data_row_count)
    lines.append("| 可计算 RPN 的行 / Rows with RPN | %d |" % len(a.valid_rows))
    lines.append("| 校验问题 / Validation issues | %d |" % len(a.issues))
    lines.append("| 高 RPN 行（RPN ≥ %d）| %d |" % (a.threshold, len(a.high_rpn_rows)))
    lines.append("| 高严重度行（S ≥ 9）| %d |" % len(a.high_severity_rows))
    lines.append("")
    lines.append("## 校验问题 / Validation Issues")
    lines.append("")
    if a.issues:
        lines.append("| 行号 (CSV) | 字段 | 问题 |")
        lines.append("| --- | --- | --- |")
        for issue in a.issues:
            lines.append("| %d | %s | %s |" % (issue.row, issue.field, issue.message))
    else:
        lines.append("无 / None.")
    lines.append("")
    lines.append("## 高严重度行（S ≥ 9）/ High-Severity Rows")
    lines.append("")
    if a.high_severity_rows:
        lines.append("| 行号 | 失效模式 | S | O | D | RPN |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for r in a.high_severity_rows:
            lines.append(_row_line(r))
    else:
        lines.append("无 / None.")
    lines.append("")
    lines.append("## RPN 前 10 / Top 10 by RPN")
    lines.append("")
    if a.top_rpn_rows:
        lines.append("| 行号 | 失效模式 | S | O | D | RPN |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for r in a.top_rpn_rows:
            lines.append(_row_line(r))
    else:
        lines.append("无 / None.")
    lines.append("")
    lines.append("## 帕累托（按 RPN 份额）/ Pareto by RPN Share")
    lines.append("")
    if a.pareto:
        lines.append("| 失效模式 | 行数 | RPN 合计 | 份额 % | 累计 % |")
        lines.append("| --- | --- | --- | --- | --- |")
        for entry in a.pareto:
            lines.append(
                "| %s | %d | %d | %.1f | %.1f |"
                % (
                    entry["failure_mode"],
                    entry["rows"],
                    entry["rpn_total"],
                    entry["share_pct"],
                    entry["cumulative_pct"],
                )
            )
    else:
        lines.append("无 / None.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(DISCLAIMER)
    lines.append("")
    return "\n".join(lines)
