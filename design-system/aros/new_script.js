<script>
// ============================================================
// AROS 每日 Alpha 雷达 - 候选股票池
// 每天基于日期种子确定性随机选出 Top 5,次日自动变化
// ============================================================
const POOL = [
  { name: '中际旭创', code: '300308.SZ', sector: '通信设备', concept: 'CPO · 光模块', base: 95,
    rev: 48.2, revG: 61.3, profit: 12.6, profitG: 82.4, gm: 33.5, roe: 18.6, eps: 0.86, est: 58.3,
    reports: 18, buys: 15, target: 108, theme: '800G/1.6T 光模块需求旺盛,AI 算力资本开支高增' },
  { name: '新易盛', code: '300502.SZ', sector: '通信设备', concept: '光模块 · 800G', base: 93,
    rev: 41.5, revG: 55.8, profit: 10.8, profitG: 76.2, gm: 31.2, roe: 16.8, eps: 0.72, est: 49.6,
    reports: 14, buys: 11, target: 106.5, theme: '800G 光模块放量,1.6T 研发领先' },
  { name: '紫光国微', code: '002049.SZ', sector: '半导体', concept: '国产芯片 · FPGA', base: 91,
    rev: 35.6, revG: 28.4, profit: 12.4, profitG: 32.1, gm: 58.9, roe: 14.2, eps: 1.02, est: 42.8,
    reports: 12, buys: 9, target: 95, theme: 'FPGA 国产替代加速,特种 IC 需求回暖' },
  { name: '沪电股份', code: '002463.SZ', sector: '电子元件', concept: 'PCB · AI 服务器', base: 88,
    rev: 28.9, revG: 21.5, profit: 6.2, profitG: 38.7, gm: 28.6, roe: 12.8, eps: 0.58, est: 18.6,
    reports: 10, buys: 7, target: 46.5, theme: 'AI 服务器 PCB 需求高增,数通板占比提升' },
  { name: '中科曙光', code: '603019.SH', sector: '计算机', concept: '算力 · 液冷', base: 87,
    rev: 96.4, revG: 15.2, profit: 11.8, profitG: 24.6, gm: 26.4, roe: 10.6, eps: 0.81, est: 38.5,
    reports: 9, buys: 7, target: 86, theme: '国产算力+液冷数据中心放量,信创+智算双轮驱动' },
  { name: '天孚通信', code: '300394.SZ', sector: '通信设备', concept: '光器件 · CPO', base: 90,
    rev: 25.8, revG: 48.2, profit: 8.9, profitG: 64.5, gm: 47.8, roe: 21.4, eps: 1.58, est: 36.2,
    reports: 13, buys: 10, target: 128, theme: 'CPO 光引擎放量,海外云厂订单饱满' },
  { name: '工业富联', code: '601138.SH', sector: '电子制造', concept: 'AI 服务器 · 代工', base: 89,
    rev: 512.6, revG: 34.5, profit: 38.4, profitG: 52.8, gm: 7.6, roe: 15.2, eps: 1.93, est: 158.2,
    reports: 11, buys: 8, target: 35.6, theme: 'AI 服务器出货放量,液冷方案占比提升' },
  { name: '寒武纪', code: '688256.SH', sector: '半导体', concept: 'AI 芯片 · 算力', base: 86,
    rev: 12.4, revG: 95.6, profit: 2.8, profitG: 120.4, gm: 61.3, roe: 8.9, eps: 0.21, est: 8.9,
    reports: 8, buys: 6, target: 1280, theme: '国产 AI 芯片放量,大模型算力需求爆发' },
  { name: '海光信息', code: '688041.SH', sector: '半导体', concept: 'CPU · DCU', base: 85,
    rev: 68.5, revG: 41.2, profit: 15.6, profitG: 58.3, gm: 63.8, roe: 17.6, eps: 0.67, est: 52.4,
    reports: 10, buys: 7, target: 168, theme: '国产 CPU+DCU 双线放量,信创替代深化' },
  { name: '浪潮信息', code: '000977.SZ', sector: '计算机', concept: 'AI 服务器 · 液冷', base: 84,
    rev: 485.2, revG: 28.6, profit: 21.4, profitG: 45.2, gm: 11.2, roe: 14.8, eps: 1.45, est: 62.8,
    reports: 9, buys: 6, target: 52.4, theme: 'AI 服务器整机出货全球前三,液冷渗透率提升' },
  { name: '剑桥科技', code: '603083.SH', sector: '通信设备', concept: '光模块 · 800G', base: 82,
    rev: 32.8, revG: 45.6, profit: 5.6, profitG: 88.4, gm: 29.4, roe: 15.8, eps: 2.06, est: 15.2,
    reports: 8, buys: 5, target: 52.8, theme: '800G 量产爬坡,北美云厂导入加速' },
  { name: '华工科技', code: '000988.SZ', sector: '电子元件', concept: '光模块 · 激光', base: 81,
    rev: 112.4, revG: 18.6, profit: 12.8, profitG: 26.4, gm: 26.8, roe: 11.6, eps: 1.27, est: 28.4,
    reports: 7, buys: 5, target: 36.5, theme: '光模块+激光装备双主业,数通产品放量' },
  { name: '光迅科技', code: '002281.SZ', sector: '通信设备', concept: '光模块 · 硅光', base: 80,
    rev: 68.2, revG: 22.4, profit: 6.8, profitG: 35.6, gm: 24.6, roe: 9.8, eps: 0.86, est: 16.8,
    reports: 6, buys: 4, target: 32.6, theme: '硅光方案量产,电信+数通双轮驱动' },
  { name: '太辰光', code: '300570.SZ', sector: '通信设备', concept: '光器件 · 光纤连接', base: 79,
    rev: 15.6, revG: 38.2, profit: 3.2, profitG: 62.4, gm: 38.2, roe: 13.2, eps: 1.41, est: 8.2,
    reports: 5, buys: 3, target: 28.5, theme: 'MPO 光连接需求高增,海外产能扩张' },
  { name: '中瓷电子', code: '003031.SZ', sector: '电子元件', concept: '陶瓷封装 · 5G', base: 78,
    rev: 18.4, revG: 25.6, profit: 4.2, profitG: 38.4, gm: 42.6, roe: 12.4, eps: 1.84, est: 9.6,
    reports: 6, buys: 4, target: 92.4, theme: '陶瓷封装龙头,汽车电子+军工需求回暖' },
  { name: '生益科技', code: '600183.SH', sector: '电子元件', concept: '覆铜板 · CCL', base: 77,
    rev: 186.4, revG: 15.8, profit: 16.8, profitG: 28.4, gm: 24.8, roe: 13.8, eps: 0.71, est: 32.4,
    reports: 7, buys: 5, target: 28.6, theme: '高速覆铜板涨价,AI 服务器 PCB 上游受益' }
];

// ---------- 确定性随机:同一天结果固定,次日自动变化 ----------
function daySeed() {
  const d = new Date();
  return d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate();
}
function rnd(seed, i) {
  const x = Math.sin(seed * 127.1 + i * 311.7) * 43758.5453;
  return x - Math.floor(x);
}
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

// ---------- 生成当日 Top 5 ----------
const seed = daySeed();
const todayList = POOL.map((s, i) => {
  const alpha = clamp(Math.round(s.base + (rnd(seed, i) - 0.5) * 16), 70, 99);
  const entry = clamp(alpha - Math.round(rnd(seed, i + 100) * 12) - 3, 55, 95);
  const hits = clamp(Math.round(alpha / 10) - 1, 4, 9);
  const heat = clamp(Math.round(72 + rnd(seed, i + 200) * 26), 55, 99);
  const flow = (0.3 + rnd(seed, i + 300) * 2.6).toFixed(2);
  return Object.assign({}, s, {
    alpha, entry, hits, heat, flow,
    ma: (65 + rnd(seed, i + 400) * 10).toFixed(1),
    rsi: (52 + rnd(seed, i + 500) * 18).toFixed(1),
    macd: (0.4 + rnd(seed, i + 600) * 2.2).toFixed(2),
    revGd: +(s.revG + (rnd(seed, i + 700) - 0.5) * 8).toFixed(1),
    profitGd: +(s.profitG + (rnd(seed, i + 800) - 0.5) * 12).toFixed(1),
    targetPct: (10 + rnd(seed, i + 900) * 8).toFixed(0),
    northDays: 1 + Math.round(rnd(seed, i + 1000) * 2),
    fundQ: (3 + rnd(seed, i + 1100) * 10).toFixed(1),
    senti: rnd(seed, i + 1200) > 0.5 ? '偏乐观' : '偏多'
  });
}).sort((a, b) => b.alpha - a.alpha).slice(0, 5);

// ---------- 渲染表格 ----------
function renderTable() {
  const tbody = document.querySelector('.alpha-table tbody');
  const medal = ['gold', 'silver', 'bronze', '', ''];
  tbody.innerHTML = todayList.map((s, idx) => {
    const stars = s.alpha >= 92 ? 5 : s.alpha >= 86 ? 4 : 3;
    const starHtml = Array.from({ length: 5 }, (_, i) =>
      '<span class="st' + (i < stars ? '' : ' off') + '">★</span>').join('');
    const hitHtml = Array.from({ length: 10 }, (_, i) =>
      '<i class="' + (i < s.hits ? 'on' : '') + '"></i>').join('');
    const ringC = s.alpha >= 88 ? '#52C41A' : s.alpha >= 80 ? '#FF9800' : '#FF4D4F';
    const bgChip = idx === 0 || (s.alpha >= 90) ? 'strong' : idx >= 3 ? 'watch' : 'neutral';
    const bgTxt = bgChip === 'strong' ? '强势' : bgChip === 'neutral' ? '中性' : '关注';
    return '<tr data-stock="' + s.name + '" data-code="' + s.code + '"' + (idx === 0 ? ' class="active"' : '') + '>' +
      '<td><span class="rank-badge ' + medal[idx] + '">' + (idx + 1) + '</span></td>' +
      '<td><span class="stock-name">' + s.name + '</span><span class="stock-code">' + s.code + '</span></td>' +
      '<td><span class="sector-chip">' + s.sector + '</span></td>' +
      '<td><span class="concept">' + s.concept + '</span></td>' +
      '<td><div class="score-cell"><span class="score">' + s.alpha + '</span><span class="stars">' + starHtml + '</span></div></td>' +
      '<td><div class="ring" style="--p:' + s.entry + ';--ring-c:' + ringC + '"><span>' + s.entry + '</span></div></td>' +
      '<td><span class="hit-bar">' + hitHtml + '</span></td>' +
      '<td><span class="chip ' + bgChip + '">' + bgTxt + '</span></td>' +
      '<td><span class="chip watch">关注</span></td>' +
      '</tr>';
  }).join('');
}

// ---------- 生成个股详情数据 ----------
function buildDetail(s) {
  const idx = POOL.findIndex(p => p.name === s.name);
  const fIdx = idx < 0 ? 0 : idx;
  const f = (k, off) => rnd(seed, fIdx * 50 + off);
  const score = s.alpha;
  const facetN = (off, spread, min, max) => {
    const v = Math.round(clamp(score + (f(fIdx, off) - 0.5) * spread, min, max));
    return v;
  };
  const fBase = facetN(0, 18, 45, 95), fTech = facetN(1, 18, 45, 95),
        fCap = facetN(2, 18, 45, 95), fNews = facetN(3, 18, 45, 95),
        fSent = facetN(4, 18, 45, 95);
  const total = Math.round((fBase + fTech + fCap + fNews + fSent) / 5);
  const totalClamped = clamp(total, 60, 95);

  const facetConf = [
    ['基本面', fBase, '#E09030,#FFB74D', '#FFB74D', fBase >= 75 ? '偏强' : fBase >= 60 ? '中性偏强' : '中性', 'rgba(255,152,0,0.15)'],
    ['技术面', fTech, '#389E0D,#95DE64', '#95DE64', fTech >= 75 ? '偏强' : fTech >= 60 ? '中性' : '偏弱', 'rgba(82,196,26,0.15)'],
    ['资金面', fCap, '#CF1322,#FF7875', '#FF7875', fCap >= 75 ? '净流入' : fCap >= 60 ? '小幅流入' : '流出', 'rgba(255,77,79,0.15)'],
    ['新闻面', fNews, '#2962FF,#40A9FF', '#40A9FF', fNews >= 75 ? '偏多' : fNews >= 60 ? '中性' : '偏空', 'rgba(41,98,255,0.15)'],
    ['情绪面', fSent, '#6D28D9,#B39DDB', '#B39DDB', fSent >= 75 ? '偏乐观' : fSent >= 60 ? '中性' : '谨慎', 'rgba(124,58,237,0.18)']
  ];

  const upDown = score >= 85 ? 'up' : score >= 75 ? 'up' : 'down';
  const verdict = score >= 88 ? '逢低建仓' : score >= 80 ? '逢低关注' : '观望为主';
  const rsiState = s.rsi >= 65 ? '偏强' : s.rsi >= 50 ? '中性' : '偏弱';
  const kdjState = f(fIdx, 10) > 0.6 ? '高位钝化' : '金叉';
  const bollState = f(fIdx, 11) > 0.6 ? '上轨突破' : '中轨上方';

  const price = s.target / (1 + (+s.targetPct) / 100);
  const p1 = (price * 1.05).toFixed(1), p2 = (price * 1.1).toFixed(1);
  const sp1 = (price * 0.97).toFixed(1), sp2 = (price * 0.94).toFixed(1);
  const tp = s.target.toFixed(1);
  const buy1 = (price * 0.99).toFixed(1), buy2 = (price * 1.02).toFixed(1);
  const sl = (price * 0.92).toFixed(1);
  const slPct = Math.round((1 - price * 0.92 / price) * 100);

  const risks = [
    '大股东计划减持 ' + (0.5 + f(fIdx, 20) * 2).toFixed(1) + '%(2026-' + (9 + Math.round(f(fIdx, 21) * 2)) + ' 实施)',
    '商誉减值 ' + (0.2 + f(fIdx, 22) * 1.2).toFixed(1) + ' 亿 · 限售解禁 ' + (2 + f(fIdx, 23) * 5).toFixed(1) + '%',
    '股东质押比例 ' + (5 + f(fIdx, 24) * 10).toFixed(1) + '%',
    '海外收入占比高,汇率波动影响毛利',
    '行业竞争加剧,毛利率承压',
    '扩产资本开支大,现金流短期承压'
  ].sort(() => f(fIdx, 25) - 0.5).slice(0, 2);

  const stratN = clamp(Math.round(score / 10) - 1, 4, 9);
  const stratTags = [
    ['动量', 8], ['趋势', 7], ['资金', 6], ['回撤', 3]
  ].map(t => '<span class="' + (t[1] >= 5 ? 'hit' : 'miss') + '">' + t[0] + ' ' + t[1] + '/10</span>').join('');

  return {
    ai: {
      tech: '均线 <span class="up">多头排列</span> · RSI ' + s.rsi + ' ' + rsiState + '<br>MACD <span class="up">金叉</span> · BOLL ' + bollState + ' · KDJ ' + kdjState,
      techTags: '<span class="hit">MA 多头</span><span class="hit">MACD 金叉</span>' + (kdjState === '金叉' ? '<span class="hit">KDJ 金叉</span>' : '<span class="miss">KDJ 超买</span>'),
      strat: stratN + ' / 10 套策略触发 · 动量 / 趋势 / 资金共振',
      stratTags: stratTags,
      senti: '情绪 <span class="' + (s.senti === '偏乐观' ? 'up' : 'up') + '">' + s.senti + '</span> · 热度 ' + s.heat + '/100<br>龙虎榜 <span class="up">净买入</span> · 股吧讨论 +' + (15 + Math.round(f(fIdx, 30) * 40)) + '%',
      inst: '主力净流入 <span class="up">+' + s.flow + ' 亿</span> · 北向 ' + s.northDays + ' 日增持<br>基金 Q2 加仓 <span class="up">+' + s.fundQ + '%</span> · 研报 ' + s.reports + ' 篇(买入 ' + s.buys + ')',
      instTags: '<span class="hit">机构买入</span><span class="hit">北向增持</span>' + (f(fIdx, 40) > 0.5 ? '<span class="hit">社保新进</span>' : ''),
      risk: '<div class="warn-line"><span class="mark">⚠</span>' + risks[0] + '</div><div class="warn-line"><span class="mark">⚠</span>' + risks[1] + '</div>',
      facets: facetConf,
      verdict: '<span class="hit">综合 ' + totalClamped + '</span><span class="hit">建议: ' + verdict + '</span>',
      prices: [
        ['压力位', p1 + ' / ' + p2, '#FF7875'],
        ['支撑位', sp1 + ' / ' + sp2, '#95DE64'],
        ['目标价位', tp + ' (+' + s.targetPct + '%)', '#40A9FF']
      ],
      prices2: [
        ['建议建仓', buy1 + '-' + buy2, '#FF7875'],
        ['参考止盈', tp, '#FF7875'],
        ['参考止损', sl + ' (-' + slPct + '%)', '#95DE64']
      ]
    },
    fund: {
      rows: [
        ['营业收入', s.rev.toFixed(1) + ' 亿', 'up', '(+' + s.revGd + '%)'],
        ['净利润', s.profit.toFixed(1) + ' 亿', 'up', '(+' + s.profitGd + '%)'],
        ['毛利率', s.gm.toFixed(1) + '%', '', ''],
        ['ROE (年化)', s.roe.toFixed(1) + '%', '', ''],
        ['每股收益', s.eps.toFixed(2) + ' 元', '', ''],
        ['一致预期净利', s.est.toFixed(1) + ' 亿', 'up', '(FY26E)']
      ],
      note: '📄 研报观点:' + s.theme + ';目标价一致预期 <b style="color:#FF7875">' + s.target.toFixed(1) + ' 元(+' + s.targetPct + '%)</b>,' + s.reports + ' 篇研报中 ' + s.buys + ' 篇买入。'
    }
  };
}

// ---------- 渲染详情 ----------
function renderDetail(tr) {
  const name = tr.dataset.stock;
  const s = todayList.find(x => x.name === name) || POOL.find(x => x.name === name);
  if (!s) return;
  const d = buildDetail(s);

  document.getElementById('aiStock').textContent = s.name + ' ' + s.code;
  document.getElementById('fundName').textContent = s.name;

  const ai = d.ai;
  const blocks = document.getElementById('aiBody').querySelectorAll('.ai-block');
  blocks[0].querySelector('.ai-val').innerHTML = ai.tech;
  blocks[0].querySelector('.ai-tags').innerHTML = ai.techTags;
  blocks[1].querySelector('.ai-val').innerHTML = ai.strat;
  blocks[1].querySelector('.ai-tags').innerHTML = ai.stratTags;
  blocks[2].querySelector('.ai-val').innerHTML = ai.senti;
  blocks[3].querySelector('.ai-val').innerHTML = ai.inst;
  blocks[3].querySelector('.ai-tags').innerHTML = ai.instTags;
  blocks[4].innerHTML = '<div class="ai-label">⚠️ 风险预告</div>' + ai.risk;

  const facets = document.getElementById('aiFacets');
  facets.innerHTML = ai.facets.map(f =>
    '<div class="facet"><span class="f-name">' + f[0] + '</span><div class="f-bar"><i style="width:' + f[1] + '%;background:linear-gradient(90deg,' + f[2] + ')"></i></div>' +
    '<span class="f-val" style="color:' + f[3] + '">' + f[1] + '</span><span class="f-tag" style="background:' + f[5] + ';color:' + f[3] + '">' + f[4] + '</span></div>'
  ).join('');
  blocks[5].querySelector('.ai-tags').innerHTML = ai.verdict;

  const pb = blocks[6].querySelectorAll('.price-box');
  pb[0].innerHTML = ai.prices.map(p => '<div class="pb"><div class="l">' + p[0] + '</div><div class="v" style="color:' + p[2] + '">' + p[1] + '</div></div>').join('');
  pb[1].innerHTML = ai.prices2.map(p => '<div class="pb"><div class="l">' + p[0] + '</div><div class="v" style="color:' + p[2] + '">' + p[1] + '</div></div>').join('');

  const fundRows = document.getElementById('fundRows');
  fundRows.innerHTML = d.fund.rows.map(r =>
    '<div class="fund-row"><span class="k">' + r[0] + '</span><span class="v ' + r[2] + '">' + r[1] + (r[3] ? ' <span style="color:var(--faint)">' + r[3] + '</span>' : '') + '</span></div>'
  ).join('') + '<div class="fund-note">' + d.fund.note + '</div>';
}

// ---------- 绑定事件 + 初始化 ----------
document.addEventListener('DOMContentLoaded', () => {
  renderTable();
  const tbody = document.querySelector('.alpha-table tbody');
  tbody.addEventListener('click', e => {
    const tr = e.target.closest('tr');
    if (!tr) return;
    document.querySelectorAll('.alpha-table tbody tr').forEach(r => r.classList.remove('active'));
    tr.classList.add('active');
    renderDetail(tr);
  });
  const first = tbody.querySelector('tr');
  if (first) renderDetail(first);
  const btn = document.getElementById('todayBtn');
  if (btn) btn.textContent = '今日 (' + todayList.length + ')';
});
</script>
