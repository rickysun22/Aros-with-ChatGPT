"""Build & inject RISK_DATA into AROS preview (风险监控 real-data module).
Re-runnable: overwrites the const RISK_DATA block before `const CAND = WATCH;`.
Data snapshot: 2026-08-11, sourced from westock MCP
  data_market_overview(type=all) + data_quote(usDJI,usIXIC,hkHSI).
"""

import json
import re

HTML = r"C:/aros/design-system/aros/preview-v2.html"
ANCHOR = "  const CAND = WATCH;"


def clamp(x, lo=0, hi=100):
    return max(lo, min(hi, x))


def map_piece(v, pts):
    """pts = list of (threshold, score) ascending; linear interpolate between."""
    pts = sorted(pts)
    if v <= pts[0][0]:
        return pts[0][1]
    if v >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        t0, s0 = pts[i]
        t1, s1 = pts[i + 1]
        if t0 <= v <= t1:
            f = (v - t0) / (t1 - t0)
            return s0 + f * (s1 - s0)
    return pts[-1][1]


# ---------- real inputs (2026-08-11) ----------
RATIO_UP = 29.14
CNT_RED, CNT_GREEN, CNT_TOTAL = 1615, 3777, 5542
UP_LIMIT, DN_LIMIT = 54, 0
MONEY = 23209.86
MONEY_5D = 91.4
MONEY_10D = 96.35
HK = -1.10
DJI = -0.21
IXIC = -0.62
PE = 21.85
PE_PCT_10Y = 94.8
RSI6 = 62.59
DIF = -15.37
TREND_LONG = "弱势下跌"
CLOSE = 3934.09
MA60 = 3995.96

# ---------- dimension scores ----------
# 大盘情绪: driven by 涨股比 (higher up-ratio = more bullish)
sent_score = round(clamp((RATIO_UP - 20) / (60 - 20) * 100))
# 资金量能: 成交额 vs 5日均 (放量利好, 缩量利空)
fund_score = round(
    map_piece(MONEY_5D, [(80, 15), (85, 25), (90, 35), (95, 45), (100, 60), (105, 70), (115, 85)])
)
# 外围影响: avg of US/HK moves
ext_vals = [DJI, IXIC, HK]
ext_avg = sum(ext_vals) / len(ext_vals)
ext_score = round(map_piece(ext_avg, [(-3, 10), (-2, 20), (-1, 35), (0, 50), (1, 75), (1.5, 85)]))
# 两融: 今日未披露 -> null
margin_score = None

# ---------- composite 机会指数 ----------
# weights excluding margin (renormalized)
w_sent, w_fund, w_ext = 0.41, 0.29, 0.29
composite = round(sent_score * w_sent + fund_score * w_fund + ext_score * w_ext)

if composite >= 60:
    verdict, vlevel = "入场信号", "up"
elif composite >= 45:
    verdict, vlevel = "中性观望", "warn"
else:
    verdict, vlevel = "离场警告", "down"

RISK_DATA = {
    "date": "2026-08-11",
    "source": "westock MCP · data_market_overview(all) + data_quote(外围)",
    "composite": composite,
    "verdict": verdict,
    "verdictLevel": vlevel,
    "summary": "市场广度极差、量能萎缩、外围偏弱、估值偏高 —— 当前风险偏多环境,建议控制仓位、防范回调,等待广度修复与放量信号。",
    "dims": {
        "sentiment": {
            "name": "大盘情绪",
            "score": sent_score,
            "level": "偏空",
            "status": "涨股比 29.1%,超 2/3 个股下跌,涨停 54 / 跌停 0,广度极差",
            "metrics": [
                {"t": "涨股比", "v": "29.1%"},
                {"t": "涨跌比", "v": "0.43"},
                {"t": "涨停/跌停", "v": "54 / 0"},
                {"t": "上涨家数", "v": "%d / %d" % (CNT_RED, CNT_TOTAL)},
            ],
        },
        "fund": {
            "name": "资金量能",
            "score": fund_score,
            "level": "偏弱",
            "status": "两市成交 2.32 万亿,缩量至 5 日均的 91.4%(10 日 96.4%),资金观望;北向自 2024-08 起暂停披露",
            "metrics": [
                {"t": "成交额", "v": "2.32 万亿"},
                {"t": "5 日均比", "v": "91.4%"},
                {"t": "10 日均比", "v": "96.4%"},
                {"t": "北向资金", "v": "暂停披露"},
            ],
        },
        "margin": {
            "name": "两融余额",
            "score": margin_score,
            "level": "今日未披露",
            "status": "westock 两融接口今日未返回有效数据,该维度暂不参与评分(诚实留白)",
            "metrics": [
                {"t": "融资余额", "v": "未披露"},
                {"t": "5 日变动", "v": "—"},
                {"t": "参与评分", "v": "否"},
            ],
        },
        "external": {
            "name": "外围影响",
            "score": ext_score,
            "level": "偏弱",
            "status": "外围普跌:港股 -1.10%% · 纳指 -0.62%% · 道指 -0.21%%,风险偏好回落(均值 %.2f%%)"
            % ext_avg,
            "metrics": [
                {"t": "恒生", "v": "%.2f%%" % HK},
                {"t": "纳指", "v": "%.2f%%" % IXIC},
                {"t": "道指", "v": "%.2f%%" % DJI},
                {"t": "外围均值", "v": "%.2f%%" % ext_avg},
            ],
        },
    },
    "reasons": [
        "涨股比仅 29.1%%,超 2/3 个股下跌(%d 涨 / %d 跌),市场广度极差" % (CNT_RED, CNT_GREEN),
        "两市成交 2.32 万亿,缩量至 5 日均的 91.4%,资金观望意愿强",
        "外围普跌(港股 -1.10% · 纳指 -0.62% · 道指 -0.21%),风险偏好回落",
        "中证全指 PE(TTM) 21.85,处 10 年 94.8% 分位,估值偏高(补充观察)",
        "中长期趋势「弱势下跌」,收盘价 %.0f 低于 MA60(%.0f),技术面承压" % (CLOSE, MA60),
    ],
    "extra": {
        "valuation": {"pe": PE, "pePct10y": PE_PCT_10Y, "level": "高估"},
        "technical": {
            "rsi6": RSI6,
            "macd": str(DIF),
            "trendLong": TREND_LONG,
            "ma": "收盘 %.0f < MA60 %.0f" % (CLOSE, MA60),
        },
    },
}

# ---------- inject ----------
js = (
    "    const RISK_DATA = "
    + json.dumps(RISK_DATA, ensure_ascii=False, indent=2)
    + ";\n\n"
    + ANCHOR
)
src = open(HTML, encoding="utf-8").read()
if "const RISK_DATA =" in src:
    # idempotent: replace existing block
    src = re.sub(r"    const RISK_DATA = \{.*?\};(\n\n)?", "", src, flags=re.S)
    assert ANCHOR in src, "anchor missing"
src = src.replace(ANCHOR, js, 1)
open(HTML, "w", encoding="utf-8").write(src)
print("OK inject RISK_DATA -> composite=%d verdict=%s(%s)" % (composite, verdict, vlevel))
print("sent=%d fund=%d ext=%d margin=%s" % (sent_score, fund_score, ext_score, margin_score))
