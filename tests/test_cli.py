"""Tests for pfmea_checker.cli: exit codes, --json, --report, --demo."""

import json

from pfmea_checker.cli import main
from pfmea_checker.core import COLUMNS

HEADER = ",".join(COLUMNS)


def make_csv(tmp_path, rows, name="pfmea.csv"):
    lines = [HEADER] + [",".join(str(c) for c in row) for row in rows]
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


GOOD = ["点焊", "虚焊", "强度不足", 8, "电极磨损", 6, "定期修磨", "电流监控", 7]  # RPN 336
BAD = ["点焊", "虚焊", "", 8, "电极磨损", 6, "定期修磨", "电流监控", 7]  # missing effect


def test_cli_valid_file_exit_0(tmp_path, capsys):
    path = make_csv(tmp_path, [GOOD])
    assert main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "336" in out
    assert "帕累托" in out


def test_cli_validation_errors_exit_2(tmp_path):
    path = make_csv(tmp_path, [BAD])
    assert main([str(path)]) == 2


def test_cli_high_rpn_alone_is_not_an_error(tmp_path):
    # RPN 336 >= 100 is a warning flag, not a validation error
    path = make_csv(tmp_path, [GOOD])
    assert main([str(path)]) == 0


def test_cli_missing_file_exit_1(tmp_path):
    assert main([str(tmp_path / "nope.csv")]) == 1


def test_cli_unknown_option_exit_1():
    assert main(["--definitely-not-an-option"]) == 1


def test_cli_no_arguments_exit_1():
    assert main([]) == 1


def test_cli_threshold_option_changes_flagging(tmp_path, capsys):
    path = make_csv(tmp_path, [GOOD])
    assert main([str(path), "--json", "--threshold", "400"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["threshold"] == 400
    assert data["high_rpn_rows"] == []
    assert data["top_rpn"][0]["rpn"] == 336


def test_json_structure(tmp_path, capsys):
    path = make_csv(tmp_path, [GOOD, BAD])
    code = main([str(path), "--json"])
    assert code == 2
    data = json.loads(capsys.readouterr().out)
    for key in (
        "file", "threshold", "row_count", "valid_rpn_rows", "issue_count",
        "issues", "high_rpn_rows", "high_severity_rows", "top_rpn", "pareto",
    ):
        assert key in data
    assert data["row_count"] == 2
    assert data["issue_count"] == 1
    assert data["issues"][0]["row"] == 3
    assert data["issues"][0]["field"] == "failure_effect"
    assert data["top_rpn"][0]["rpn"] == 336
    assert data["pareto"][0]["failure_mode"] == "虚焊"


def test_report_file_written(tmp_path, capsys):
    path = make_csv(tmp_path, [GOOD, BAD])
    report = tmp_path / "report.md"
    code = main([str(path), "--report", str(report)])
    assert code == 2
    text = report.read_text(encoding="utf-8")
    assert "PFMEA 检查报告" in text
    assert "校验问题" in text
    assert "Top 10" in text or "RPN 前 10" in text
    assert "帕累托" in text
    assert "不代替工程师批准" in text
    assert "does not approve" in text


def test_demo_flag_writes_sample_and_exit_0(tmp_path):
    demo = tmp_path / "demo.csv"
    assert main(["--demo", str(demo)]) == 0
    assert demo.exists()
    lines = demo.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == HEADER
    assert len(lines) == 9  # header + 8 data rows


def test_demo_file_itself_has_validation_errors(tmp_path):
    demo = tmp_path / "demo.csv"
    assert main(["--demo", str(demo)]) == 0
    assert main([str(demo)]) == 2
