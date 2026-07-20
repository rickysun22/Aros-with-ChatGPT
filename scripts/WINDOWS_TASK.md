# AROS 本机每日运行 (Windows 任务计划)

把 AROS 的日级筛选闭环放到你自己的 Windows 机器上跑——**沙箱/服务器常有网络代理拦截东方财富,本机不挡**,这是设计用法。

## 0. 准备 Python 环境

仓库根目录:

```bat
python -m venv .venv
.venv\Scripts\pip install -e .
```

然后编辑 `scripts/aros_daily.bat` 与 `scripts/aros_backfill.bat`,把 `PYTHON` 指向
`.venv\Scripts\python.exe`(默认已经是这个相对路径,一般无需改)。

## 1. 一次性全 A 股历史回填(首次必跑)

```bat
scripts\aros_backfill.bat
```

- 拉取全市场(~5300 只)日线历史(默认自 2024-01-01)写入本地 `data/aros.db`。
- 耗时约 20~60 分钟,取决于网络;写入是幂等 upsert,中断重跑即可。
- **这一步必须在「每日运行」之前完成**,否则没有历史数据可筛。

## 2. 注册每日自动运行

右键 `scripts/aros_install_task.bat` → **以管理员身份运行**。
会创建计划任务 `AROS Daily Alpha`:每个工作日 18:30 执行 `aros_daily.bat`。

手动验证一次:

```bat
scripts\aros_daily.bat
```

## 3. 日常发生了什么

`aros_daily.bat` 调用:

```
python main.py research alpha run --universe all_a
```

每天幂等执行:增量同步(仅补新交易日)→ 全市场共识筛选(4.2)→
Alpha 报告(4.4)→ 校准回填(4.6)→ 决策后验(4.5)→ 可选模拟盘(4.7/4.8)
→ 到第 60 个交易日生成校验报告。结果落在 `reports/<run_date>/`。

> 资金流(4.3)默认开启,抓取失败时自动降级为中性 50,不会中断运行。

## 4. 管理命令

```bat
schtasks /query   /tn "AROS Daily Alpha"     :: 查看
schtasks /delete  /tn "AROS Daily Alpha" /f  :: 删除
```

## 5. 其他池子(可选)

`--universe` 还支持:

| 值       | 含义                                  |
| -------- | ------------------------------------- |
| `all_a`  | 全 A 股(~5300,本机部署默认)          |
| `csi800` | 中证 800(沪深300+中证500,~688 只)    |
| `watchlist` | 自选池(配合 `--watchlist 文件.txt`) |
| `custom` | 固定代码列表(配置 `universe.custom_codes`) |

> 全市场每日同步会向数据源发起约 5300 次增量请求,属正常量级;
> 若数据源限流,失败的个股会跳过并在次日重试(增量、幂等)。
