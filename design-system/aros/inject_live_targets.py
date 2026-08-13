"""把后端 live_sim 生成的 targets_*.json 注入 preview-v2.html 的 LIVE_TARGETS 常量。

同时从本地 qfq_cache 读取 A/B/H 选股的真实前复权日线，并尝试从东财 stock/get
拉取行业(f100)/概念(f104)，一并注入。这样前端即使浏览器端 JSONP 被拦截，也能
用后端已准备好的真实数据渲染 Alpha 雷达表。
"""

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

LIVE = Path("C:/aros/reports/_data/live_sim")
HTML = Path("C:/aros/design-system/aros/preview-v2.html")
QFQ = Path("C:/aros/reports/_data/qfq_cache")
META_CACHE = Path("C:/aros/reports/_data/live_sim/meta_cache.json")


def load_meta_cache() -> dict:
    """读取本机网络取回的真实行业/概念缓存(由 WeStock data_profile / data_industry_chain 产出)。

    沙箱外网被限制,无法直连东财/akshare,因此真实 meta 需经由已连接的 westock-mcp
    连接器(走用户本机网络)取回并落盘到 meta_cache.json,注入脚本只负责读取。
    """
    if META_CACHE.exists():
        try:
            return json.load(open(META_CACHE, encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def em_secid(code: str) -> str:
    market = "1" if code[:1] in ("6", "9") else "0"
    return f"{market}.{code}"


def em_stock_meta(code: str) -> dict:
    """从东财 push2 stock/get 取行业/概念。失败优雅回退。"""
    params = urllib.parse.urlencode(
        {
            "fltt": "2",
            "invt": "2",
            "fields": "f57,f58,f100,f104,f127",
            "secid": em_secid(code),
        }
    )
    url = f"https://push2.eastmoney.com/api/qt/stock/get?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    for _ in range(2):
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                d = json.loads(r.read().decode("utf-8")).get("data") or {}
            con = str(d.get("f104") or "").strip()
            # f104 偶尔返回数字或空串，过滤掉
            if not con or con.isdigit():
                con = ""
            return {
                "sec": str(d.get("f100") or "").strip(),
                "con": con,
                "sw2": str(d.get("f127") or "").strip(),
            }
        except Exception:
            time.sleep(1.0)
    return {"sec": "", "con": "", "sw2": ""}


def qfq_klines(code: str, limit: int = 120) -> dict:
    """从本地 qfq_cache 读最近 limit 条收盘，返回 {d:[date...], c:[close...]}。"""
    # qfq_cache 文件名可能带 sh/sz/bj 前缀，也可能不带；两种都试试
    candidates = [code]
    if not re.match(r"^(sh|sz|bj)", code):
        for pre in ("sh", "sz", "bj"):
            candidates.append(pre + code)
    else:
        candidates.append(re.sub(r"^(sh|sz|bj)", "", code))
    for c in candidates:
        p = QFQ / f"{c}.json"
        if not p.exists():
            continue
        try:
            raw = json.load(open(p, encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            items = sorted(raw.items())
            if len(items) > limit:
                items = items[-limit:]
            return {
                "d": [k for k, _ in items],
                "c": [float(v) for _, v in items],
            }
        except Exception:
            continue
    return {}


files = sorted([p for p in LIVE.glob("targets_*.json") if "_review_" not in p.name])
if not files:
    raise SystemExit("未找到 targets_YYYYMMDD.json(A/B/H),请先运行 live_sim.py 选股")
latest = files[-1]
data = json.load(open(latest, encoding="utf-8"))

strategies = data.get("strategies", {})
all_codes = sorted({re.sub(r"^(sh|sz|bj)", "", c) for group in strategies.values() for c in group})

print(f"[inject] 读取 {latest.name} 共 {len(all_codes)} 只 A/B/H 选股")

meta_cache = load_meta_cache()
meta = {}
klines = {}
for code in all_codes:
    bare = re.sub(r"^(sh|sz|bj)", "", code)
    klines[bare] = qfq_klines(bare)
    # 优先用本机网络取回的真实 meta 缓存;沙箱连不上东财时 em_stock_meta 只会回退空串
    m = dict(meta_cache.get(bare) or {})
    if not m.get("sec") and not m.get("con"):
        m = em_stock_meta(bare)
        if not m["con"]:
            m["con"] = m["sw2"] or m["sec"]
    m.setdefault("sec", "")
    m.setdefault("con", "")
    meta[bare] = m
    print(
        f"[inject] {bare} sec={m['sec'][:16]:<16} con={m['con'][:30]:<30} k={len(klines[bare].get('c') or [])}"
    )

out = {
    "sel_date": data.get("sel_date", latest.stem.split("_")[-1]),
    "entry_date": data.get("entry_date", ""),
    "strategies": strategies,
    "meta": meta,
    "klines": klines,
}

js = (
    "  // ===LIVE_TARGETS_START===\n"
    "  // A/B/H 三策略真实选股结果(含后端预取行业/概念/K线),来源: "
    + str(latest).replace("\\", "/")
    + "\n"
    "  const LIVE_TARGETS = " + json.dumps(out, ensure_ascii=False, indent=2) + ";\n"
    "  // ===LIVE_TARGETS_END===\n"
)
s = open(HTML, encoding="utf-8").read()
pat = r"  // ===LIVE_TARGETS_START===.*?  // ===LIVE_TARGETS_END===\n"
if re.search(pat, s, re.DOTALL):
    s2 = re.sub(pat, js, s, flags=re.DOTALL)
else:
    s2 = s.replace("  const SEED_WATCH = [", js + "  const SEED_WATCH = [", 1)
open(HTML, "w", encoding="utf-8").write(s2)
print("[inject] 已写入", HTML)
