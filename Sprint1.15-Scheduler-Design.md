# Sprint 1.15 — 定时生成 + 推送（Scheduler + Notifier）

## 目标
让日报 / 自选股追踪可以「定时自动跑 + 推送到某个地方」。运营价值高，但**不要求任何外部凭据**：
webhook 推送在没有 URL 时自动跳过，调度器照样能跑（默认 console 打印）。

## 设计
- **`Notifier` 抽象 + 三种实现**（`src/scheduler/notify.py`）：
  - `ConsoleNotifier`（默认，打印）、`FileNotifier`（追加到文件）、`WebhookNotifier`（HTTP POST JSON）。
  - `WebhookNotifier` 为 best-effort：网络异常被吞掉；`webhook_url` 为 `None` 时直接 no-op。
  - `build_notifier(SchedulerConfig)` 按配置构造。
- **`Scheduler`**（`src/scheduler/engine.py`）：
  - `run_ntimes(task, interval, n)`：跑 n 次（测试用，间隔可设为 0）。
  - `run_loop(task, interval, stop_event)`：循环跑，`stop_event`(threading.Event) 可中断，部署环境能干净退出。
  - `task` 是零参 callable，返回字符串正文；tick 中 task 异常被捕获，不会让循环挂掉。
- **配置**：`SchedulerConfig`（`notifier_type` / `webhook_url` / `file_path`）挂在 `AppConfig.scheduler`；`settings.yaml` 暴露。
- **CLI `schedule` 命令**：
  - `--report [CODES...] [--universe POOL] [--backtest]` 或 `--watchlist [--backtest]` 选择定时任务；
  - `--every N`（分钟）设间隔，`--once` 只跑一轮（便于验证 / CI）。

## 无未来函数
调度器只是「按间隔重复调用已有的生成逻辑」，不引入新数据窗口；生成的报告/摘要与手动运行完全一致（窗口仍收敛于 as_of）。

## 测试
- `tests/test_scheduler.py`：console 打印、file 落盘、webhook 无 URL 不报错、build_notifier 三类、run_ntimes 次数正确、CLI `--once` 冒烟。
- 全离线，无需网络或凭据。

## 改动文件
- `src/scheduler/notify.py`（新增）
- `src/scheduler/engine.py`（新增）
- `src/scheduler/__init__.py`（新增）
- `src/core/config.py`（`SchedulerConfig` + `AppConfig.scheduler`）
- `config/settings.yaml`（`scheduler` 段）
- `main.py`（导入；新增 `schedule` 命令）
- `tests/test_scheduler.py`（新增，7 项测试）
