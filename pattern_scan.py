#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AROS 形态扫描计算引擎（供「形态实时提醒」自动化调用）
- 输入：westock data_kline 的多码批量原始返回 JSON（见 __main__ 解析）
- 输出：stdout 打印结构化 JSON 摘要；同时把可读 markdown 提醒写到 out 文件
- 形态识别规则 1:1 移植自 preview-v2.html 的 detectPatterns（收盘价峰谷规则引擎）
  仅依赖收盘价序列（与前端一致），含振幅过滤、双顶/双底/头肩顶/底 + 颈线/测距目标 + 破位确认
"""
import sys, json

# AROS 16 只候选池（名称映射；与 preview-v2.html SEED_WATCH 一致）
NAMES = {
    "300308": "中际旭创", "300502": "新易盛", "300394": "天孚通信", "002463": "沪电股份",
    "002049": "紫光国微", "601138": "工业富联", "688256": "寒武纪", "688041": "海光信息",
    "603019": "中科曙光", "688008": "澜起科技", "000063": "中兴通讯", "300750": "宁德时代",
    "002594": "比亚迪", "600519": "贵州茅台", "601318": "中国平安", "600900": "长江电力",
}

WINDOW = 36  # 与前端 mktBuildDetail 的 patCs = cs.slice(-36) 保持一致


def _double_top(cs, highs, n, rec, min_in):
    for a in range(len(highs) - 1):
        for b in range(a + 1, len(highs)):
            h1, h2 = highs[a], highs[b]
            if h2["i"] - h1["i"] < 4 or h2["i"] - h1["i"] > 30:
                continue
            sp = abs(h1["p"] - h2["p"]) / h1["p"]
            if sp > 0.04 or h2["p"] > h1["p"] * 1.04:
                continue
            v = min_in(h1["i"], h2["i"]); neck = v["p"]; lastP = cs[n - 1]; broken = lastP < neck
            conf = max(40, min(92, 52 + round((0.04 - sp) / 0.04 * 18) + round(rec(h2["i"]) * 16) + (10 if broken else 0)))
            return [{"type": "双顶", "dir": "bearish", "conf": conf, "title": "双顶（看空反转）",
                     "desc": "近 %d 个交易日出现两个相近高点（%.2f / %.2f），%s" % (
                         h2["i"] - h1["i"], h1["p"], h2["p"],
                         ("已跌破颈线 %.2f，形态成立。" % neck) if broken else ("颈线 %.2f 未破，仍待确认。" % neck)),
                     "levels": [{"label": "颈线", "price": "%.2f" % neck},
                                {"label": "测距目标", "price": "%.2f" % (neck - (max(h1["p"], h2["p"]) - neck))}]}]
    return []


def _double_bottom(cs, lows, n, rec, max_in):
    for a in range(len(lows) - 1):
        for b in range(a + 1, len(lows)):
            l1, l2 = lows[a], lows[b]
            if l2["i"] - l1["i"] < 4 or l2["i"] - l1["i"] > 30:
                continue
            sp = abs(l1["p"] - l2["p"]) / l1["p"]
            if sp > 0.05 or l2["p"] < l1["p"] * 0.95:
                continue
            v = max_in(l1["i"], l2["i"]); neck = v["p"]; lastP = cs[n - 1]; broken = lastP > neck
            conf = max(40, min(92, 52 + round((0.05 - sp) / 0.05 * 18) + round(rec(l2["i"]) * 16) + (10 if broken else 0)))
            return [{"type": "双底", "dir": "bullish", "conf": conf, "title": "双底（看多反转）",
                     "desc": "近 %d 个交易日出现两个相近低点（%.2f / %.2f），%s" % (
                         l2["i"] - l1["i"], l1["p"], l2["p"],
                         ("已突破颈线 %.2f，形态成立。" % neck) if broken else ("颈线 %.2f 未破，仍待确认。" % neck)),
                     "levels": [{"label": "颈线", "price": "%.2f" % neck},
                                {"label": "测距目标", "price": "%.2f" % (neck + (neck - min(l1["p"], l2["p"])))}]}]
    return []


def _hs_top(cs, highs, n, rec, min_in):
    if len(highs) < 3:
        return []
    for a in range(len(highs) - 2):
        for b in range(a + 1, len(highs) - 1):
            for c in range(b + 1, len(highs)):
                LS, Hh, RS = highs[a], highs[b], highs[c]
                if not (Hh["i"] > LS["i"] and Hh["i"] < RS["i"]):
                    continue
                if Hh["p"] <= LS["p"] or Hh["p"] <= RS["p"]:
                    continue
                sh = abs(LS["p"] - RS["p"]) / LS["p"]
                if sh > 0.10 or RS["i"] - LS["i"] > 40:
                    continue
                v1 = min_in(LS["i"], Hh["i"]); v2 = min_in(Hh["i"], RS["i"]); neck = (v1["p"] + v2["p"]) / 2
                lastP = cs[n - 1]; broken = lastP < neck
                conf = max(42, min(93, 50 + round((0.10 - sh) / 0.10 * 16) + round(rec(RS["i"]) * 14) + (12 if broken else 0)))
                return [{"type": "头肩顶", "dir": "bearish", "conf": conf, "title": "头肩顶（看空反转）",
                         "desc": "左肩 %.2f / 头部 %.2f（最高） / 右肩 %.2f，两肩相近；%s" % (
                             LS["p"], Hh["p"], RS["p"],
                             ("已跌破颈线 %.2f，形态成立。" % neck) if broken else ("颈线 %.2f 未破，待确认。" % neck)),
                         "levels": [{"label": "颈线", "price": "%.2f" % neck},
                                    {"label": "测距目标", "price": "%.2f" % (neck - (Hh["p"] - neck))}]}]
    return []


def _hs_bottom(cs, lows, n, rec, max_in):
    if len(lows) < 3:
        return []
    for a in range(len(lows) - 2):
        for b in range(a + 1, len(lows) - 1):
            for c in range(b + 1, len(lows)):
                LS, Hh, RS = lows[a], lows[b], lows[c]
                if not (Hh["i"] > LS["i"] and Hh["i"] < RS["i"]):
                    continue
                if Hh["p"] >= LS["p"] or Hh["p"] >= RS["p"]:
                    continue
                sh = abs(LS["p"] - RS["p"]) / LS["p"]
                if sh > 0.10 or RS["i"] - LS["i"] > 40:
                    continue
                v1 = max_in(LS["i"], Hh["i"]); v2 = max_in(Hh["i"], RS["i"]); neck = (v1["p"] + v2["p"]) / 2
                lastP = cs[n - 1]; broken = lastP > neck
                conf = max(42, min(93, 50 + round((0.10 - sh) / 0.10 * 16) + round(rec(RS["i"]) * 14) + (12 if broken else 0)))
                return [{"type": "头肩底", "dir": "bullish", "conf": conf, "title": "头肩底（看多反转）",
                         "desc": "左肩 %.2f / 头部 %.2f（最低） / 右肩 %.2f，两肩相近；%s" % (
                             LS["p"], Hh["p"], RS["p"],
                             ("已突破颈线 %.2f，形态成立。" % neck) if broken else ("颈线 %.2f 未破，待确认。" % neck)),
                         "levels": [{"label": "颈线", "price": "%.2f" % neck},
                                    {"label": "测距目标", "price": "%.2f" % (neck + (neck - Hh["p"]))}]}]
    return []


def detect_patterns(cs_in):
    cs = [v for v in (cs_in or []) if isinstance(v, (int, float)) and v == v]
    n = len(cs)
    if n < 14:
        return {"list": [], "marks": []}
    W = 3
    highs, lows = [], []
    for i in range(W, n - W):
        isH = all(cs[j] <= cs[i] for j in range(i - W, i + W + 1))
        isL = all(cs[j] >= cs[i] for j in range(i - W, i + W + 1))
        if isH:
            highs.append({"i": i, "p": cs[i]})
        if isL:
            lows.append({"i": i, "p": cs[i]})

    def rec(idx):
        if idx >= n - 14:
            return 1
        if idx >= n - 26:
            return 0.6
        return 0.25

    def min_in(a, b):
        seg = cs[a:b + 1]; m = min(seg); return {"p": m, "i": a + seg.index(m)}

    def max_in(a, b):
        seg = cs[a:b + 1]; m = max(seg); return {"p": m, "i": a + seg.index(m)}

    lo, hi = min(cs), max(cs)
    amp = (hi - lo) / lo
    if amp < 0.12:
        return {"list": [{"type": "震荡", "dir": "neutral",
                          "conf": round(55 + (0.12 - amp) / 0.12 * 25),
                          "title": "箱体震荡（方向待突破）",
                          "desc": "近 %d 个交易日波动幅度仅 %.1f%%，呈区间整理（%.2f–%.2f），等待方向选择。" % (n, amp * 100, lo, hi),
                          "levels": [{"label": "上沿", "price": "%.2f" % hi}, {"label": "下沿", "price": "%.2f" % lo}]}],
                "marks": [{"i": n - 1, "p": hi, "kind": "neck", "dir": "bull"},
                          {"i": n - 1, "p": lo, "kind": "neck", "dir": "bear"}]}
    list_ = []
    list_ += _double_top(cs, highs, n, rec, min_in)
    list_ += _double_bottom(cs, lows, n, rec, max_in)
    list_ += _hs_top(cs, highs, n, rec, min_in)
    list_ += _hs_bottom(cs, lows, n, rec, max_in)
    list_.sort(key=lambda x: -x["conf"])
    return {"list": list_[:3], "marks": []}


def compose_md(summary):
    L = []
    L.append("## AROS 形态扫描 · 收盘提醒")
    L.append("")
    L.append("扫描 %d 只候选池 · 命中反转形态 %d 只" % (summary["scanned"], summary["with_pattern"]))
    L.append("")
    if not summary["alerts"]:
        L.append("今日（最近 %d 个交易日）未识别到明确反转形态，继续持有观察。" % WINDOW)
    else:
        for a in summary["alerts"]:
            L.append("### %s %s" % (a["code"], a["name"]))
            for p in a["patterns"]:
                arrow = "🔴" if p["dir"] == "bearish" else ("🟢" if p["dir"] == "bullish" else "⚪")
                L.append("- %s **%s** 置信度 %d%%" % (arrow, p["title"], p["conf"]))
                L.append("  %s" % p["desc"])
                L.append("  %s" % " / ".join("%s %s" % (lv["label"], lv["price"]) for lv in p["levels"]))
            L.append("")
    L.append("> 规则引擎识别（非 AI 生成），颈线/目标位为技术测算参考，不构成投资建议。")
    return "\n".join(L)


def main():
    if len(sys.argv) < 2:
        print("usage: pattern_scan.py <westock_batch_json> [msg_out_md]", file=sys.stderr)
        sys.exit(1)
    inp = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "C:/aros/_pattern_msg.md"
    raw = json.load(open(inp, encoding="utf-8"))

    items = []
    d = raw.get("data") if isinstance(raw, dict) else None
    if isinstance(d, dict) and isinstance(d.get("data"), list):
        items = d["data"]
    elif isinstance(d, dict) and "nodes" in d:
        items = [{"symbol": None, "data": d}]

    alerts, scanned = [], 0
    for it in items:
        sym = it.get("symbol") or ""
        bare = "".join(ch for ch in sym if ch.isdigit())
        name = NAMES.get(bare, sym)
        nodes = (it.get("data") or {}).get("nodes") or []
        nodes = sorted(nodes, key=lambda x: x.get("date", ""))
        closes = [float(x["last"]) for x in nodes if "last" in x]
        if len(closes) < 14:
            continue
        scanned += 1
        res = detect_patterns(closes[-WINDOW:])
        pats = [p for p in res["list"] if p["type"] != "震荡"]
        if pats:
            alerts.append({"code": bare, "name": name, "patterns": pats})

    summary = {"scanned": scanned, "with_pattern": len(alerts), "alerts": alerts}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    open(out, "w", encoding="utf-8").write(compose_md(summary))
    print("MSG_WRITTEN:" + out, file=sys.stderr)


if __name__ == "__main__":
    main()
