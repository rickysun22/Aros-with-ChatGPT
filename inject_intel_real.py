"""inject_intel_real.py
把股票情报页(buildIntel)覆盖 16 只的「机构动向/研报覆盖/券商评级/盈利预测」从
rndInfo/RPT_POOL 随机伪造,改为东方财富真实研报(stock_research_report_em)预取内联(同 MG_EM 模式)。
机构持仓/北向/主力净流入等暂缺真实源的字段改为诚实占位(需接入数据源)。
"""

import json
import math
import re
import time

import akshare as ak

CODES = [
    "300308",
    "300502",
    "300394",
    "002463",
    "002049",
    "601138",
    "688256",
    "688041",
    "603019",
    "688008",
    "000063",
    "300750",
    "002594",
    "600519",
    "601318",
    "600900",
]


def clean(v):
    if v is None:
        return None
    try:
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
    except Exception:
        pass
    return v


def fetch(code):
    try:
        df = ak.stock_research_report_em(symbol=code)
    except Exception as e:
        print("  [skip] %s %s: %s" % (code, type(e).__name__, e))
        return None
    if df is None or len(df) == 0:
        print("  [empty] %s" % code)
        return None
    df = df.copy()
    if "日期" in df.columns:
        df = df.sort_values("日期", ascending=False)
    reps = []
    for _, r in df.head(8).iterrows():
        g = lambda k: clean(r.get(k))
        eps = g("2026-盈利预测-收益")
        pe = g("2026-盈利预测-市盈率")
        reps.append(
            {
                "broker": str(g("机构")) if g("机构") is not None else None,
                "rating": str(g("东财评级")) if g("东财评级") is not None else None,
                "title": str(g("报告名称")) if g("报告名称") is not None else None,
                "date": (str(g("日期"))[:10] if g("日期") is not None else None),
                "eps": round(float(eps), 2) if eps is not None else None,
                "pe": round(float(pe), 1) if pe is not None else None,
            }
        )
    count = int(len(df))
    buys = int(sum(1 for _, r in df.iterrows() if str(r.get("东财评级")) == "买入"))
    return {"count": count, "buys": buys, "reports": reps}


INTEL_REAL = {}
for c in CODES:
    print("fetch", c)
    res = fetch(c)
    if res:
        INTEL_REAL[c] = res
    time.sleep(0.25)

# ---------- 注入 HTML ----------
HTML = "design-system/aros/preview-v2.html"
html = open(HTML, encoding="utf-8").read()

# 1) INTEL_REAL 内联(在 const RISK_DATA 之前,带 marker)
const_js = "const INTEL_REAL = " + json.dumps(INTEL_REAL, ensure_ascii=False) + ";"
marker = (
    "// ===INTEL_REAL_START=== 真实研报(东方财富 stock_research_report_em, inject_intel_real.py 生成) ===INTEL_REAL_END===\n"
    + const_js
    + "\n"
)
pat = r"// ===INTEL_REAL_START===.*?===INTEL_REAL_END===\nconst INTEL_REAL = .*?;\n"
if re.search(pat, html, re.S):
    html = re.sub(pat, marker, html, flags=re.S)
else:
    html = html.replace("const RISK_DATA = {", marker + "const RISK_DATA = {", 1)

# 2) 替换伪造块(RPT_BROKERS ... buildIntel 结束)为干净 buildIntel
NEW_BLOCK = r"""    // ---- 真实研报(东方财富 stock_research_report_em 预取,见 INTEL_REAL) ----
    function buildIntel(s) {
      const F = s.faces || { fund: 50, tech: 50, flow: 50, news: 50, sent: 50 };
      const faceNames = { fund: '基本面', tech: '技术面', flow: '资金面', news: '新闻面', sent: '情绪面' };
      const faceIcons = { fund: '🏦', tech: '📈', flow: '💰', news: '📰', sent: '🔥' };
      const vText = v => v >= 70 ? '强' : (v >= 45 ? '中' : '弱');
      const faces = Object.keys(FACE_W).map(k =>
        '<div class="intel-facet"><span class="intel-fname">' + faceIcons[k] + ' ' + faceNames[k] + ' <b>' + vText(F[k]) + '</b></span>' +
        '<div class="intel-fbar"><i style="width:' + F[k] + '%" class="' + (F[k] >= 70 ? 'good' : (F[k] >= 45 ? 'mid' : 'bad')) + '"></i></div>' +
        '<span class="intel-fval">' + F[k] + '</span></div>'
      ).join('');
      const fScore = faceScore(s);
      const kScore = kTechScore(s);
      const nws = INTEL_NEWS[s.c] || [];
      // === 真实研报(东方财富) ===
      const real = (typeof INTEL_REAL !== 'undefined' && INTEL_REAL[s.c]) ? INTEL_REAL[s.c] : null;
      const reports = real ? real.reports : [];
      const repCount = real ? real.count : 0;
      const buyCount = real ? real.buys : 0;
      const rateClsOf = r => (r === '买入' ? 'buy' : (r === '增持' ? 'hold' : (r === '减持' || r === '卖出' ? 'sell' : 'mid')));
      const rpList = reports.map(r =>
        '<div class="intel-rp">' +
        '<div class="rp-row1"><span class="rp-brk">' + (r.broker || '—') + '</span>' +
        '<span class="rp-date">' + (r.date || '—') + '</span>' +
        '<span class="rp-rate ' + rateClsOf(r.rating) + '">' + (r.rating || '—') + '</span>' +
        (r.eps != null ? '<span class="rp-tp">26E EPS ' + r.eps + '</span>' : '') +
        (r.pe != null ? '<span class="rp-cat">26E PE ' + r.pe + '</span>' : '') +
        '</div>' +
        '<div class="rp-row2"><span class="rp-logic">' + (r.title || '') + '</span></div>' +
        '</div>'
      ).join('');
      const rpHtml =
        '<div class="intel-sec"><div class="intel-sec-t">📑 研报覆盖<span class="intel-sec-sub">真实数据 · 东方财富研报接口 · 近3月 ' + repCount + ' 篇 · 买入 ' + buyCount + ' 家</span></div>' +
        (reports.length ? '<div class="intel-rp-list">' + rpList + '</div>' : '<div class="intel-news neutral"><b>暂无</b><span>近3月无公开研报覆盖</span></div>') +
        '</div>';
      // === 机构动向:真实字段暂缺,诚实占位(需接入港交所/基金季报/东方财富资金流) ===
      const instHtml =
        '<div class="intel-sec"><div class="intel-sec-t">🏛️ 机构动向<span class="intel-sec-sub">演示占位 · 需接入数据源</span></div>' +
        '<div class="intel-note">主力净流入 / 北向资金 / 基金持仓 等字段需接入真实数据源(港交所沪深港通、基金季报、东方财富资金流),当前为原型演示占位,不代表真实机构动向。</div></div>';
      const newsScore = nws.length ? 50 + nws.reduce((a, n) => a + n.sent, 0) * 60 / nws.length : 50;
      const newsHtml =
        '<div class="intel-sec"><div class="intel-sec-t">📰 新闻情报<span class="intel-sec-sub">' + nws.length + ' 条重点新闻</span></div>' +
        (nws.length
          ? nws.map(n => '<div class="intel-news ' + (n.sent > 0 ? 'pos' : 'neg') + '">' +
            '<span class="intel-nmeta"><em class="intel-ntime">' + n.time + '</em><em class="intel-nsrc">' + n.src + '</em></span>' +
            '<span class="intel-ntag">' + (n.sent > 0 ? '利好' : '利空') + '</span>' +
            '<span class="intel-ntext">' + n.t + '</span>' +
            '<em class="intel-nimp">' + n.imp + '</em></div>').join('')
          : '<div class="intel-news neutral"><b>暂无</b><span>近期无重大公开新闻</span></div>') +
        '</div>';
      const verdict = fScore * 0.45 + kScore * 0.2 + newsScore * 0.35;
      const vCls = verdict >= 62 ? 'pos' : (verdict >= 48 ? 'neutral' : 'neg');
      const vTxt = verdict >= 62 ? '偏多' : (verdict >= 48 ? '中性' : '偏空');
      const vDesc = verdict >= 62 ? '基本面与机构资金共振,新闻面边际改善,可逢低关注' :
        (verdict >= 48 ? '多空因素均衡,等待量能或催化确认方向' : '基本面与情绪面承压,建议观望,等待信号反转');
      // === 公司概览 bull/bear:由真实评级共识推导(非随机) ===
      let bull = '—', bear = '—';
      if (real && reports.length) {
        const ups = reports.filter(r => r.rating === '买入' || r.rating === '增持').length;
        const downs = reports.filter(r => r.rating === '卖出' || r.rating === '减持').length;
        if (ups > downs) { bull = '机构评级以买入/增持为主(' + ups + '家),盈利预期上修'; bear = '需关注估值与行业周期波动风险'; }
        else if (downs > ups) { bull = '—'; bear = '机构评级偏谨慎(' + downs + '家卖出/减持),基本面承压'; }
        else { bull = '机构观点分歧,等待催化确认'; bear = '行业竞争与政策不确定性仍存'; }
      } else { bull = '暂无真实研报,无法推导机构观点'; bear = '—'; }
      const mv = (parseFloat(s.lb) * 100).toFixed(0);
      const ovHtml =
        '<div class="intel-sec"><div class="intel-sec-t">🏢 公司概览</div>' +
        '<div class="intel-ov-intro">' + s.n + ' 是国内' + s.sec + '领域核心公司,主营' + s.con.replace(' · ', '/') + '等业务,市值约 ' + mv + ' 亿元。</div>' +
        '<div class="intel-ov-grid">' +
        '<div class="intel-ov-item"><span class="ov-k">🔑 核心看点</span><span class="ov-v">' + bull + '</span></div>' +
        '<div class="intel-ov-item"><span class="ov-k">⚠️ 风险提示</span><span class="ov-v down">' + bear + '</span></div>' +
        '</div></div>';
      return '<div class="intel-head"><div class="intel-hname">' + s.n + ' <span>' + s.c + '</span></div>' +
        '<div class="intel-hpx"><span class="' + (s.chg.startsWith('-') ? 'down' : 'up') + '">' + s.px + ' ' + s.chg + '</span><span class="intel-hmeta">' + s.sec + ' · ' + s.con + ' · 市值约 ' + mv + ' 亿</span></div></div>' +
        '<div class="intel-verdict ' + vCls + '"><span class="iv-chip">综合研判 · ' + vTxt + '</span><span class="iv-desc">' + vDesc + '</span>' +
        '<span class="iv-scores">5面 ' + fScore.toFixed(0) + ' · K线 ' + kScore.toFixed(0) + ' · 新闻 ' + newsScore.toFixed(0) + '</span></div>' +
        ovHtml +
        '<div class="intel-sec"><div class="intel-sec-t">🎯 5 面评分<span class="intel-sec-sub">原型演示评分(非实时计算)</span></div>' + faces + '</div>' +
        instHtml +
        '<div class="intel-cols">' +
        '<div class="intel-col-left">' + rpHtml + '</div>' +
        '<div class="intel-col-right">' + newsHtml + '</div>' +
        '</div>';
    }
"""

start = html.index("    const RPT_BROKERS = [")
end_anchor = "    // ---- 实时行情(腾讯财经"
end = html.index(end_anchor)
html = html[:start] + NEW_BLOCK + html[end:]

# 3) 新增 .intel-note 样式(接在 .intel-sec-sub 规则后)
note_css = (
    "  .intel-note { font-size: 11.5px; color: var(--faint); line-height: 1.6; "
    "background: rgba(245,158,11,.08); border: 1px dashed rgba(245,158,11,.4); "
    "border-radius: 8px; padding: 8px 11px; margin-top: 8px; }\n"
)
anchor = (
    "  .intel-sec-sub { font-size: 11px; color: var(--faint); font-weight: 600; margin-left: 6px; }"
)
if anchor in html and ".intel-note {" not in html:
    html = html.replace(anchor, anchor + "\n" + note_css, 1)

open(HTML, "w", encoding="utf-8").write(html)
print(
    "DONE: injected INTEL_REAL for", len(INTEL_REAL), "codes; rewrote buildIntel; added .intel-note"
)
