# -*- coding: utf-8 -*-
"""把后端 live_sim 生成的 targets_*.json 注入 preview-v2.html 的 LIVE_TARGETS 常量。"""
import json, os, re
from pathlib import Path

LIVE = Path("C:/aros/reports/_data/live_sim")
HTML = Path("C:/aros/design-system/aros/preview-v2.html")

files = sorted([p for p in LIVE.glob("targets_*.json") if "_review_" not in p.name])
if not files:
    raise SystemExit("未找到 targets_YYYYMMDD.json(A/B/H),请先运行 live_sim.py 选股")
latest = files[-1]
data = json.load(open(latest, encoding="utf-8"))
out = {
    "sel_date": data.get("sel_date", latest.stem.split("_")[-1]),
    "entry_date": data.get("entry_date", ""),
    "strategies": data.get("strategies", {})
}
js = (
    "  // ===LIVE_TARGETS_START===\n"
    "  // A/B/H 三策略真实选股结果,来源: " + str(latest).replace("\\", "/") + "\n"
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
print("[inject]", latest, "->", HTML)
