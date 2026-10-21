# pfmea-checker

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

面向制造业工艺工程师的 PFMEA 工作表检查工具。把 PFMEA 导出为 CSV 后，本工具自动校验表格结构（必填项、S/O/D 取值）、计算每行的 RPN、标出高 RPN 与高严重度行，并生成帕累托汇总和 Markdown 评审报告，帮助工程师在正式评审前快速定位问题行。

> **重要**：本工具辅助人工评审，不代替工程师批准 PFMEA。所有标记只是提示，处置决定须由负责工程师作出。
> This tool assists review and does not approve a PFMEA on behalf of an engineer.

[English](#english)

## 功能

- **结构校验**：`severity` / `occurrence` / `detection` 必须是 1–10 的整数；`failure_mode`、`failure_effect`、`failure_cause`、`prevention_control`、`detection_control` 不得为空；缺少必需的列也会报错。每个问题都带 CSV 行号（表头为第 1 行，第一行数据为第 2 行）。
- **RPN 计算与标记**：RPN = S × O × D；RPN ≥ 阈值的行被单独标出（`--threshold` 可调，默认 100）。
- **高严重度单列**：严重度 S ≥ 9 的行无论 RPN 高低都单独标记——低 RPN 不能掩盖高严重度，这正是只看 RPN 容易漏掉的风险。
- **帕累托分析**：按失效模式汇总 RPN 份额并给出累计百分比，快速找出占大头的失效模式。
- **多种输出**：控制台摘要、`--json` 机器可读输出、`--report` 生成 Markdown 评审报告。
- **示例数据**：`--demo` 生成 8 行示例 PFMEA（故意含 1 行漏填、1 行 S/O/D 非法），方便演示校验效果。

**范围说明**：v1 只做 RPN 与结构校验，**不包含** AIAG-VDA 的 AP（行动优先级）查表。AP 评定请按 AIAG-VDA 手册由工程师完成，本工具的 RPN 标记不能替代 AP。

## 安装

```bash
pip install git+https://github.com/aoyexiaoqi/pfmea-checker.git
```

从源码安装：

```bash
git clone https://github.com/aoyexiaoqi/pfmea-checker.git
cd pfmea-checker
pip install -e .
```

需要 Python 3.9 及以上版本，无第三方运行时依赖。

## 快速开始

```bash
pfmea-check --demo demo.csv   # 生成示例文件
pfmea-check demo.csv          # 检查它（示例含故意设置的问题，退出码为 2）
```

输出节选：

```text
PFMEA 检查：demo.csv
数据行 8（可计算 RPN 7），校验问题 2 个

校验问题 / Validation issues:
  第 7 行 [detection_control] detection_control 为空（必填项）
  第 9 行 [detection] detection 不是整数：'abc'

高严重度行（S ≥ 9，不看 RPN）：
  第 5 行  RPN 54  S=9 O=2 D=3  螺丝漏锁
  第 6 行  RPN 54  S=9 O=3 D=2  电容极性反插

高 RPN 行（RPN ≥ 100）：
  第 2 行  RPN 336  S=8 O=6 D=7  焊点虚焊
  第 7 行  RPN 144  S=6 O=4 D=6  胶量不足
  ...

帕累托（按 RPN 份额）/ Pareto:
  焊点虚焊             行数 1  RPN 合计 336  份额 38.3%  累计 38.3%
  胶量不足             行数 1  RPN 合计 144  份额 16.4%  累计 54.7%
  ...
```

## 用法

```bash
pfmea-check pfmea.csv                        # 控制台摘要
pfmea-check pfmea.csv --threshold 200        # 自定义 RPN 阈值
pfmea-check pfmea.csv --json                 # JSON 输出，接其他工具/脚本
pfmea-check pfmea.csv --report report.md     # 生成 Markdown 评审报告
pfmea-check --demo demo.csv                  # 仅生成示例文件
```

Markdown 报告包含：概览计数、校验问题表、高严重度行清单、RPN 前 10 表、帕累托表。

## CSV 格式

第一行必须是表头，列名精确如下（列的顺序不限，多余的列会被忽略）：

| 列名 | 含义 | 要求 |
| --- | --- | --- |
| `process_step` | 过程步骤 | 文本 |
| `failure_mode` | 失效模式 | 必填，非空 |
| `failure_effect` | 失效影响 | 必填，非空 |
| `severity` | 严重度 S | 整数 1–10 |
| `failure_cause` | 失效原因 | 必填，非空 |
| `occurrence` | 频度 O | 整数 1–10 |
| `prevention_control` | 现行预防控制 | 必填，非空 |
| `detection_control` | 现行探测控制 | 必填，非空 |
| `detection` | 探测度 D | 整数 1–10 |

示例：

| process_step | failure_mode | failure_effect | severity | failure_cause | occurrence | prevention_control | detection_control | detection |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 电阻点焊 | 焊点虚焊 | 焊接强度不足，零件脱落 | 8 | 电极帽磨损 | 6 | 电极帽定周期修磨 | 焊接电流实时监控 | 7 |
| 螺丝锁付 | 螺丝漏锁 | 组件松动，功能失效 | 9 | 操作员漏作业 | 2 | 防错计数器 | 电批扭矩自动记录 | 3 |

文件编码建议 UTF-8（带 BOM 亦可）；从 Excel/WPS 导出时选择「CSV UTF-8」即可。

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 无校验错误（高 RPN、高严重度属于警告标记，不算错误） |
| `2` | 发现校验错误（必填项缺失、S/O/D 非法或缺列） |
| `1` | 文件或用法错误（文件不存在、无法解析、参数错误） |

## English

**pfmea-checker** is a CLI for manufacturing process engineers that checks a PFMEA worksheet exported as CSV. It validates the worksheet structure (required fields, S/O/D ratings), computes RPN per row, flags high-RPN rows and — separately — high-severity rows (S ≥ 9) regardless of RPN, and produces a Pareto summary plus a Markdown review report.

```bash
pip install git+https://github.com/aoyexiaoqi/pfmea-checker.git
pfmea-check --demo demo.csv   # write a sample PFMEA CSV (with deliberate errors)
pfmea-check demo.csv          # console summary; exit 2 = validation errors
pfmea-check pfmea.csv --threshold 200 --report report.md
pfmea-check pfmea.csv --json
```

- Required columns: `process_step, failure_mode, failure_effect, severity, failure_cause, occurrence, prevention_control, detection_control, detection`. Ratings must be integers from 1 to 10; the five text fields in the README table above must be non-empty. Every issue is reported with its CSV row number (header = row 1).
- Exit codes: `0` no validation errors (flags are warnings), `2` validation errors found, `1` file/usage error.
- Scope: RPN and structural checks only. **AIAG-VDA Action Priority (AP) lookup is not included** — AP must be assessed by an engineer per the AIAG-VDA handbook.
- This tool assists review and does not approve a PFMEA on behalf of an engineer.

## License

[MIT](LICENSE) © aoyexiaoqi
