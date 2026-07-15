# Sprint 1.14 — 报告 HTML 可视化（Report HTML Visualization）

## 目标
给每日研究日报增加一个自包含、可离线打开的 HTML 渲染（`DailyReport.to_html()`），
用内联 CSS + 内联 SVG 柱状图把「综合分排名」画出来，并保留 markdown 版的全部列
（含 1.10 的回测指标）。`report` 命令新增 `--format html`。

## 设计
- **`DailyReport.to_html(include_detail=True)`**（`src/report/engine.py`）：
  - 内联 `<style>`（无外部依赖，离线可用），浅色主题、表格 hover、卡片网格。
  - **SVG 横向柱状图**：按 `composite_score` 归一化到 0..1 画条形，标注代码与分值；
    `min..max` 缩放，空报告显示占位提示。
  - **表格**：与 markdown 同列（排名/代码/综合分/各 score/最新价/日涨跌/数据日期/新鲜），
    开启回测时追加「回测收益%/最大回撤%/Sharpe/基准%」。
  - **明细卡片**：`include_detail` 时按候选渲染卡片网格（综合分、各 score、最新价/日涨跌、回测）。
  - 文本经 HTML 转义（`& < >`），避免注入。
- **配置**：`ReportConfig.format` 的 `Literal` 扩展为 `markdown | json | html`。
- **CLI**：`report ... --format html` 走 `to_html`；`--out report.html` 可直接落盘。

## 无未来函数
HTML 只是展示层，数据完全来自已生成的 `DailyReport`（其窗口已在 1.8/1.10 收敛于 as_of），
渲染本身不引入任何新数据或窗口，零泄漏。

## 测试
- `test_to_html_renders_chart_and_table`：含 `<!DOCTYPE html>`、`<svg>`+柱状、`A`/`B`、`综合分`、明细。
- `test_to_html_backtest_columns`：开启回测时含「回测收益」「Sharpe」列。

## 改动文件
- `src/report/engine.py`（`DailyReport.to_html`）
- `src/core/config.py`（`ReportConfig.format` 增加 `html`）
- `main.py`（`report --format` 文案 + html 分支）
- `tests/test_report.py`（2 项 HTML 测试）
