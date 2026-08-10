# AROS 前端 (React + Vite + Tailwind)

A 股研究操作系统 AROS 的投研终端前端。通过 **FastAPI 桥接服务**直接调用 AROS 后端的
`DataManager` + `IndicatorEngine` + `FactorEngine`,把真实行情、技术指标(MA/RSI/MACD/KDJ/BOLL)
与 8 个因子在浏览器里实时呈现。后端未起或无数据时,前端自动使用演示数据兜底,不会白屏。

## 架构

```
AROS 后端 (Python)                前端 (React)
┌─────────────────────┐          ┌──────────────────────────┐
│ DataManager          │   HTTP   │ Vite + React + Tailwind   │
│ IndicatorEngine  ───┼──/api───▶│ 融合版投研终端 (图表/指标 │
│ FactorEngine        │  (CORS)  │ /因子/Alpha雷达/告警…)    │
└─────────────────────┘          └──────────────────────────┘
   api_server.py                  npm run dev → :5173
```

## 1. 启动后端桥接服务(接入真实数据)

```bash
cd Aros-with-ChatGPT          # 仓库根
python -m venv .venv && source .venv/bin/activate   # 或用任意 Python 3.12+
pip install -r requirements-api.txt

# 准备数据(二选一):
#  A) 演示用合成数据(无需网络/akshare):
python seed_demo.py
#  B) 真实行情(需网络,默认 AKShare 或 settings.yaml 里改 astockdata):
python main.py sync --list
python main.py sync --code 600000        # 逐只同步,或写脚本批量

# 启动 API(默认 :8000)
python api_server.py
# 健康检查: http://localhost:8000/api/health
```

> `akshare` 在 AROS 内为**懒加载**,桥接服务只做读取与计算,因此运行 `api_server.py` 时
> 不必安装 akshare;只有真正 `sync` 抓数时才需要。

## 2. 启动前端

```bash
cd Aros-with-ChatGPT/frontend
npm install
npm run dev          # 开发服务器 :5173,自动把 /api 代理到 http://localhost:8000
```

打开 http://localhost:5173 即可。顶栏右侧的状态点:
- 绿 = 已连接 AROS API(蜡烛图/指标/因子为真实引擎计算)
- 黄 = 演示数据(后端未起或暂无同步数据)

### 生产构建(静态,可部署到任意环境)

```bash
npm run build        # 输出到 dist/
npm run preview      # 本地预览构建产物
```

部署到云端(如 CloudStudio)时,通过环境变量指定 API 地址:
`VITE_API_BASE=https://your-aros-api npm run build`,前端即同源/跨域访问该 API。

## 3. 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 服务状态 / 数据源 / 已加载指标·因子 |
| GET | `/api/stocks` | 标的列表(代码/名称) |
| GET | `/api/bars/{code}` | 单标的 OHLCV + 逐根涨跌 |
| GET | `/api/indicators/{code}` | 技术指标(MA/RSI/MACD/KDJ/BOLL) |
| GET | `/api/factors/{code}` | 指标 + 8 因子(由 FactorEngine 计算) |
| GET | `/api/indices/{code}` | 指数日线 |
| GET | `/api/market` | 上证/深证/沪深300 快照 |

所有价格单位元(CNY),日期 ISO `YYYY-MM-DD`,NaN 序列化为 `null`。

## 4. 设计

视觉规范见仓库根 `design-system/MASTER.md`(深色 TradingView 基底 × macOS 面板,
A 股红涨绿跌 `#EF4444`/`#22C55E`,等宽数字字体)。

## 目录

```
src/
  api.ts                 # API 客户端(带 mock 兜底)
  mock.ts                # 演示数据
  types.ts               # 类型
  ui.tsx                 # 通用 UI(Pct/Dot/Card)
  components/            # Sidebar/Topbar/各面板/CandleChart(手绘Canvas)/IndicatorPanel
  App.tsx                # 编排:探测 API → live/mock → 渲染
```
