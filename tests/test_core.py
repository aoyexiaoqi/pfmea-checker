"""Tests for pfmea_checker.core: validation, RPN, flagging, Pareto."""

import pytest

from pfmea_checker.core import COLUMNS, analyze, write_demo

HEADER = ",".join(COLUMNS)


def make_csv(tmp_path, rows, header=HEADER, name="pfmea.csv"):
    lines = [header] + [",".join(str(c) for c in row) for row in rows]
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def good_row(**overrides):
    row = {
        "process_step": "点焊",
        "failure_mode": "虚焊",
        "failure_effect": "强度不足",
        "severity": 8,
        "failure_cause": "电极磨损",
        "occurrence": 6,
        "prevention_control": "定期修磨",
        "detection_control": "电流监控",
        "detection": 7,
    }
    row.update(overrides)
    return [row[c] for c in COLUMNS]


def issues_for(analysis, field_name):
    return [i for i in analysis.issues if i.field == field_name]


# ---------------------------------------------------------------- RPN math

def test_rpn_math(tmp_path):
    path = make_csv(tmp_path, [good_row()])  # 8 x 6 x 7
    result = analyze(path)
    assert result.rows[0].rpn == 336


def test_valid_file_has_no_issues(tmp_path):
    path = make_csv(tmp_path, [good_row(), good_row(failure_mode="烧穿")])
    result = analyze(path)
    assert result.issues == []
    assert result.data_row_count == 2
    assert len(result.valid_rows) == 2


# ------------------------------------------------------- missing text fields

def test_missing_text_field_reports_csv_row_number(tmp_path):
    rows = [good_row(), good_row(), good_row(failure_effect="")]
    result = analyze(make_csv(tmp_path, rows))
    found = issues_for(result, "failure_effect")
    assert len(found) == 1
    assert found[0].row == 4  # header is row 1, third data row is row 4


def test_missing_prevention_control_detected(tmp_path):
    result = analyze(make_csv(tmp_path, [good_row(prevention_control="")]))
    found = issues_for(result, "prevention_control")
    assert len(found) == 1
    assert found[0].row == 2


def test_whitespace_only_field_counts_as_empty(tmp_path):
    result = analyze(make_csv(tmp_path, [good_row(failure_mode="   ")]))
    assert len(issues_for(result, "failure_mode")) == 1


# ------------------------------------------------------------- rating checks

def test_non_integer_rating_is_issue_and_blocks_rpn(tmp_path):
    result = analyze(make_csv(tmp_path, [good_row(severity="high")]))
    assert len(issues_for(result, "severity")) == 1
    assert result.rows[0].rpn is None
    assert result.valid_rows == []


def test_out_of_range_rating_high(tmp_path):
    result = analyze(make_csv(tmp_path, [good_row(severity=11)]))
    assert len(issues_for(result, "severity")) == 1
    assert result.rows[0].rpn is None


def test_out_of_range_rating_low(tmp_path):
    result = analyze(make_csv(tmp_path, [good_row(detection=0)]))
    assert len(issues_for(result, "detection")) == 1
    assert result.rows[0].rpn is None


def test_float_rating_rejected(tmp_path):
    result = analyze(make_csv(tmp_path, [good_row(occurrence="2.5")]))
    assert len(issues_for(result, "occurrence")) == 1
    assert result.rows[0].rpn is None


def test_empty_rating_is_issue(tmp_path):
    result = analyze(make_csv(tmp_path, [good_row(detection="")]))
    assert len(issues_for(result, "detection")) == 1


def test_missing_column_reported_at_row_1(tmp_path):
    header = ",".join(c for c in COLUMNS if c != "detection")
    row = [v for c, v in zip(COLUMNS, good_row()) if c != "detection"]
    result = analyze(make_csv(tmp_path, [row], header=header))
    found = issues_for(result, "detection")
    assert any(i.row == 1 for i in found)


# ---------------------------------------------------------------- flagging

def test_threshold_boundary_rpn_equal_flags(tmp_path):
    # 5 x 5 x 4 = 100 -> flagged at the default threshold (>= threshold)
    result = analyze(make_csv(tmp_path, [good_row(severity=5, occurrence=5, detection=4)]))
    assert [r.rpn for r in result.high_rpn_rows] == [100]


def test_below_threshold_not_flagged(tmp_path):
    # 4 x 4 x 6 = 96 < 100
    result = analyze(make_csv(tmp_path, [good_row(severity=4, occurrence=4, detection=6)]))
    assert result.high_rpn_rows == []


def test_custom_threshold(tmp_path):
    path = make_csv(tmp_path, [good_row()])  # RPN 336
    assert analyze(path, threshold=500).high_rpn_rows == []
    assert len(analyze(path, threshold=300).high_rpn_rows) == 1


def test_high_severity_flagged_even_with_low_rpn(tmp_path):
    # 9 x 1 x 1 = 9: far below the RPN threshold, still severity-flagged
    result = analyze(make_csv(tmp_path, [good_row(severity=9, occurrence=1, detection=1)]))
    assert result.high_rpn_rows == []
    assert [r.number for r in result.high_severity_rows] == [2]


def test_severity_8_not_high_severity_even_with_high_rpn(tmp_path):
    # 8 x 8 x 10 = 640
    result = analyze(make_csv(tmp_path, [good_row(severity=8, occurrence=8, detection=10)]))
    assert result.high_severity_rows == []
    assert [r.rpn for r in result.high_rpn_rows] == [640]


# ------------------------------------------------------------------ Pareto

def test_pareto_cumulative_math(tmp_path):
    rows = [
        good_row(failure_mode="A", severity=10, occurrence=6, detection=5),  # 300
        good_row(failure_mode="B", severity=10, occurrence=5, detection=4),  # 200
        good_row(failure_mode="C", severity=5, occurrence=5, detection=4),   # 100
    ]
    pareto = analyze(make_csv(tmp_path, rows)).pareto
    assert [p["failure_mode"] for p in pareto] == ["A", "B", "C"]
    assert [p["rpn_total"] for p in pareto] == [300, 200, 100]
    assert [p["share_pct"] for p in pareto] == pytest.approx([50.0, 33.3, 16.7], abs=0.05)
    assert [p["cumulative_pct"] for p in pareto] == pytest.approx([50.0, 83.3, 100.0], abs=0.05)
    assert pareto[-1]["cumulative_pct"] == 100.0


def test_pareto_groups_rows_by_failure_mode(tmp_path):
    rows = [
        good_row(failure_mode="虚焊"),                                # 336
        good_row(failure_mode="虚焊", severity=2, occurrence=2, detection=2),  # 8
        good_row(failure_mode="烧穿", severity=5, occurrence=5, detection=4),   # 100
    ]
    pareto = analyze(make_csv(tmp_path, rows)).pareto
    assert pareto[0]["failure_mode"] == "虚焊"
    assert pareto[0]["rows"] == 2
    assert pareto[0]["rpn_total"] == 344


def test_pareto_excludes_rows_without_rpn(tmp_path):
    rows = [good_row(), good_row(failure_mode="坏行", severity="x")]
    pareto = analyze(make_csv(tmp_path, rows)).pareto
    assert [p["failure_mode"] for p in pareto] == ["虚焊"]


def test_top_rpn_sorted_descending_and_limited(tmp_path):
    rows = [
        good_row(failure_mode="M%d" % i, severity=(i % 10) + 1, occurrence=5, detection=5)
        for i in range(12)
    ]
    top = analyze(make_csv(tmp_path, rows)).top_rpn_rows
    assert len(top) == 10
    rpns = [r.rpn for r in top]
    assert rpns == sorted(rpns, reverse=True)


# -------------------------------------------------------------------- demo

def test_write_demo_produces_eight_rows(tmp_path):
    demo = write_demo(tmp_path / "demo.csv")
    result = analyze(demo)
    assert result.data_row_count == 8


def test_demo_contains_demonstrable_validation_errors(tmp_path):
    demo = write_demo(tmp_path / "demo.csv")
    result = analyze(demo)
    by_pair = {(i.row, i.field) for i in result.issues}
    # row 7 = 涂胶 row with empty detection_control
    assert (7, "detection_control") in by_pair
    # row 9 = 贴标 row with detection = "abc"
    assert (9, "detection") in by_pair
    # both S=9 rows are severity-flagged
    assert len(result.high_severity_rows) == 2
