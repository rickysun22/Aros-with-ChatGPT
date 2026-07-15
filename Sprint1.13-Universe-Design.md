# Sprint 1.13 — Universe 股票池管理（Stock-pool Management）

## 目标
提供一个「命名股票池」作为下游命令（尤其是 `report`）的统一候选来源。之前 `report` 每次都要手敲
`codes`，现在可以用 `universe add POOL CODE...` 建池，再用 `report --universe POOL` 一键出日报。

## 设计
- **新增 `UniversePool` ORM 模型**（`src/universe/models.py`，挂在 `core.database.Base`）：
  - 列：`name`(PK)、`description`、`codes_json`(JSON 列表)、`created_at`、`updated_at`。
- **`UniverseEngine`**（`src/universe/engine.py`，session 化，复用共享库）：
  - `add_codes(name, codes)`：池不存在则创建；成员去重 + 字典序排序后存回。
  - `remove_codes(name, codes)`：差集后存回。
  - `get_codes(name)` / `exists(name)` / `list_pools()` / `delete(name)`。
- **CLI `universe` 命令**：`add | remove | list | show | delete`。
- **`report` 接入 `--universe NAME`**：若指定，从 `UniverseEngine.get_codes` 解析出候选 codes；
  否则仍可用位置参数手传。两种互斥，给了 `--universe` 即以池为准。

## 与现有模块的边界
- Watchlist（1.9）自带成员表，不依赖 universe；universe 是「候选池」概念，专注喂 `report`。
- Ranking/Backtest 配置不变；universe 只解决「codes 从哪来」的问题，不改排序/回测语义。

## 测试
- `tests/test_universe.py`：增/查（去重+排序）、删、未知池返回空、列举/删除、exists。
- CLI 冒烟：`universe add` + `universe list`。
- 全部用隔离 in-memory sqlite，不依赖真实数据。

## 改动文件
- `src/universe/models.py`（新增）
- `src/universe/engine.py`（新增）
- `src/universe/__init__.py`（新增）
- `main.py`（导入 `UniverseEngine`；新增 `universe` 命令；`report` 加 `--universe`）
- `tests/test_universe.py`（新增，6 项测试）
