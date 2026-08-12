#!/usr/bin/env python
# 取真实全国两融余额时间序列(沪+深相加≈全国),内联进 preview-v2.html 作为 MG_EM 常量。
# 数据源: akshare macro_china_market_margin_sh / _sz (东方财富融资融券报告, 日频, 2010-至今)
import akshare as ak, json, re, sys

HTML = r"C:\aros\design-system\aros\preview-v2.html"
N = 260  # 取最近约 1 年交易日

def load(side):
    fn = ak.macro_china_market_margin_sh if side == 'sh' else ak.macro_china_market_margin_sz
    df = fn()
    df = df[['日期', '融资买入额', '融资余额', '融券余额', '融资融券余额']].copy()
    df['日期'] = df['日期'].astype(str)
    for c in ['融资买入额', '融资余额', '融券余额', '融资融券余额']:
        df[c] = df[c].astype(float)
    df = df.dropna(subset=['融资融券余额'])
    return df

sh = load('sh'); sz = load('sz')
m = sh.merge(sz, on='日期', suffixes=('_sh', '_sz'))
for c in ['融资买入额', '融资余额', '融券余额', '融资融券余额']:
    m[c] = m[c + '_sh'].fillna(0) + m[c + '_sz'].fillna(0)
m = m[['日期', '融资买入额', '融资余额', '融券余额', '融资融券余额']].tail(N).reset_index(drop=True)

# 转 亿元(float) 压缩体积
def yi(v): return round(v / 1e8, 1)
MG = {
    'd': m['日期'].tolist(),
    'rzmre': [yi(x) for x in m['融资买入额']],
    'rzye':  [yi(x) for x in m['融资余额']],
    'rqye':  [yi(x) for x in m['融券余额']],
    'rzrqye':[yi(x) for x in m['融资融券余额']],
}
n = len(MG['d'])
last = MG['rzrqye'][-1]; p5 = MG['rzrqye'][max(0, n-6)]; p20 = MG['rzrqye'][max(0, n-21)]
chg5 = (last / p5 - 1) * 100; chg20 = (last / p20 - 1) * 100
score = max(5, min(95, 50 + chg20 * 6))
print('最新日期', MG['d'][-1])
print('两融余额(亿)', last, '| 融资余额(亿)', MG['rzye'][-1], '| 融券余额(亿)', MG['rqye'][-1])
print('融资买入额(亿)', MG['rzmre'][-1], '| 占两市成交(按2.32万亿)%.1f%%' % (MG['rzmre'][-1] / 23200 * 100))
print('20日变动 %.2f%% | 5日变动 %.2f%% | 情绪热度分 %.0f' % (chg20, chg5, score))

js = 'const MG_EM = ' + json.dumps(MG, ensure_ascii=False, separators=(',', ':')) + ';'
block = '// ===MG_EM_START=== 真实全国两融余额序列(沪+深, akshare macro_china_market_margin_sh/sz, 单位:亿元) ===MG_EM_END===\n' + js + '\n'

with open(HTML, 'r', encoding='utf-8') as f:
    src = f.read()
src = re.sub(r'// ===MG_EM_START===.*?// ===MG_EM_END===\n', '', src, flags=re.S)
src = src.replace('const RISK_DATA = {', block + 'const RISK_DATA = {', 1)
with open(HTML, 'w', encoding='utf-8') as f:
    f.write(src)
print('已注入 MG_EM (', n, '个交易日) 到', HTML)
