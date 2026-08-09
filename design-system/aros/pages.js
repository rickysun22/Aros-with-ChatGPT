// ===== 页面渲染器 + 侧边栏导航 =====
(function () {

  // ---------- 小工具 ----------
  function esc(s) { return String(s); }
  function sparkline(pts, w, h, color) {
    const min = Math.min.apply(null, pts), max = Math.max.apply(null, pts);
    const r = max - min || 1;
    const step = w / (pts.length - 1);
    const d = pts.map((p, i) => (i === 0 ? 'M' : 'L') + (i * step).toFixed(1) + ',' + (h - ((p - min) / r) * (h - 8) - 4).toFixed(1)).join(' ');
    return '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" style="display:block;width:100%">' +
      '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="1.6" stroke-linejoin="round"/>' +
      '<path d="' + d + ' L ' + w + ',' + h + ' L 0,' + h + ' Z" fill="' + color + '" opacity="0.10"/>' +
      '<circle cx="' + w + '" cy="' + (h - ((pts[pts.length - 1] - min) / r) * (h - 8) - 4).toFixed(1) + '" r="2.4" fill="' + color + '"/></svg>';
  }
  function ichBody(item, dates) {
    return '';
  }
  function kpis(items) {
    return '<div class="pg-kpis">' + items.map(k =>
      '<div class="pg-kpi"><div class="pg-kpi-top"><span class="pg-kpi-t">' + k.t + '</span><span class="pg-kpi-i">' + (k.icon || '') + '</span></div>' +
      '<div class="pg-kpi-v ' + (k.cls || '') + '">' + k.v + '</div>' +
      (k.d ? '<div class="pg-kpi-d ' + (k.cls || '') + '">' + k.d + '</div>' : '') +
      (k.extra ? '<div class="pg-kpi-x">' + k.extra + '</div>' : '') + '</div>'
    ).join('') + '</div>';
  }
  function table(head, rows) {
    return '<div class="pg-table"><table><thead><tr>' + head.map(h => '<th>' + h + '</th>').join('') + '</tr></thead><tbody>' +
      rows.map(r => '<tr>' + r.map(c => '<td>' + c + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>';
  }
  function bars(items) {
    return '<div class="pg-bars">' + items.map(b =>
      '<div class="pg-bar"><div class="pg-bar-n">' + b.name + '</div><div class="pg-bar-track"><i style="width:' + b.val + '%;background:linear-gradient(90deg,' + b.color + ')"></i></div>' +
      '<div class="pg-bar-v">' + b.txt + '</div></div>'
    ).join('') + '</div>';
  }
  function list(items) {
    return '<div class="pg-list">' + items.map(it =>
      '<div class="pg-list-item"><div class="pg-li-main"><div class="pg-li-t">' + it.t + '</div>' +
      (it.sub ? '<div class="pg-li-sub">' + it.sub + '</div>' : '') + '</div>' +
      (it.tag ? '<span class="pg-li-tag ' + (it.cls || '') + '">' + it.tag + '</span>' : '') +
      (it.time ? '<span class="pg-li-time">' + it.time + '</span>' : '') + '</div>'
    ).join('') + '</div>';
  }
  function grid(items) {
    return '<div class="pg-grid">' + items.map(g =>
      '<div class="pg-grid-card"><div class="pg-gc-icon">' + g.icon + '</div><div class="pg-gc-t">' + g.t + '</div>' +
      (g.sub ? '<div class="pg-gc-sub">' + g.sub + '</div>' : '') +
      (g.tag ? '<span class="pg-gc-tag ' + (g.cls || '') + '">' + g.tag + '</span>' : '') + '</div>'
    ).join('') + '</div>';
  }

  // ---------- 页面定义 ----------
  const INDEX_BLOCKS = [
    { t: 'index', d: { title: '主要指数行情', dates: ['07/28', '07/29', '07/30', '07/31', '08/03', '08/04', '08/05', '08/06', '08/07', '08/08'], items: [
      { n: '上证指数', v: '3,298.42', chg: '+12.63', pct: '+0.38%', c: '#FF4D4F', extra: '成交 4,182 亿', px: [3268.5, 3280.2, 3275.6, 3288.1, 3295.4, 3290.7, 3302.5, 3296.2, 3291.8, 3298.42] },
      { n: '深证成指', v: '10,756.83', chg: '+48.21', pct: '+0.45%', c: '#FF9800', extra: '成交 5,976 亿', px: [10620.5, 10672.8, 10705.4, 10688.2, 10726.6, 10712.1, 10758.9, 10744.5, 10731.8, 10756.83] },
      { n: '创业板指', v: '2,215.66', chg: '+15.30', pct: '+0.70%', c: '#40A9FF', extra: '成交 2,341 亿', px: [2178.4, 2201.6, 2194.8, 2212.2, 2205.5, 2224.9, 2216.4, 2208.7, 2219.3, 2215.66] },
      { n: '科创 50', v: '986.54', chg: '-4.12', pct: '-0.42%', c: '#13C2C2', extra: '成交 886 亿', px: [1002.8, 998.2, 995.6, 990.4, 993.1, 989.5, 992.8, 985.6, 988.3, 986.54] }
    ] } },
    { t: 'cards', d: [
      { title: '涨跌家数', val: '3,142 涨 / 1,876 跌', note: '涨停 87 · 跌停 12', color: '#FF4D4F' },
      { title: '北向资金', val: '+56.4 亿', note: '连续 3 日净流入', color: '#2962FF' },
      { title: '两市成交', val: '10,158 亿', note: '较昨日 +4.2%', color: '#722ED1' },
      { title: '市场温度', val: '68° 偏热', note: '情绪指标 · 谨慎追高', color: '#FF9800' }
    ] },
    { t: 'flowchart', d: { title: '板块资金流向 · 主力净流入(亿元)', dates5: ['08/04', '08/05', '08/06', '08/07', '08/08'], dates10: ['07/28', '07/29', '07/30', '07/31', '08/03', '08/04', '08/05', '08/06', '08/07', '08/08'], groups: [
{ n: '通信', c: '#FF4D4F', day: 28.6, d5: [12.4, 18.2, 9.6, 22.4, 28.6], d10: [5.2, 8.6, 15.4, 11.2, 20.8, 12.4, 18.2, 9.6, 22.4, 28.6] , px: [3245.3, 3190.92, 3142.32, 3248.29, 3342.89, 3299.1, 3285.35, 3362.02, 3349.75, 3265.8]},
{ n: '电子', c: '#FF9800', day: 32.5, d5: [15.8, 8.2, 20.4, 14.6, 32.5], d10: [6.4, 10.2, 12.8, 18.6, 9.4, 15.8, 8.2, 20.4, 14.6, 32.5] , px: [3786.16, 3953.32, 3969.21, 3891.57, 3944.75, 4007.65, 3919.36, 3886.93, 4039.75, 4128.6]},
{ n: '计算机', c: '#40A9FF', day: 12.4, d5: [3.2, 5.8, -1.4, 8.6, 12.4], d10: [-2.4, 0.8, 2.6, 5.2, 1.8, 3.2, 5.8, -1.4, 8.6, 12.4] , px: [2663.5, 2670.28, 2788.83, 2819.95, 2770.67, 2808.59, 2865.17, 2801.25, 2751.7, 2846.2]},
{ n: '汽车', c: '#13C2C2', day: 8.9, d5: [2.1, -1.5, 4.8, 6.2, 8.9], d10: [-3.2, -1.8, 0.6, 3.4, 1.2, 2.1, -1.5, 4.8, 6.2, 8.9] , px: [3172.23, 3108.27, 3042.75, 3133.33, 3222.22, 3187.96, 3193.37, 3283.54, 3269.79, 3172.5]},
{ n: '机械设备', c: '#722ED1', day: 6.5, d5: [1.2, 3.4, 2.8, 4.6, 6.5], d10: [-2.8, -1.2, 0.4, 2.2, 0.8, 1.2, 3.4, 2.8, 4.6, 6.5] , px: [2273.69, 2221.0, 2284.44, 2343.39, 2307.38, 2298.88, 2353.29, 2333.1, 2255.13, 2276.4]},
{ n: '电力设备', c: '#EB2F96', day: 5.2, d5: [5.6, -3.4, -2.8, 1.2, 5.2], d10: [8.2, 3.6, -4.2, -1.8, 2.4, 5.6, -3.4, -2.8, 1.2, 5.2] , px: [3096.31, 3135.09, 3219.83, 3184.64, 3169.52, 3269.89, 3286.89, 3168.25, 3143.43, 3234.8]},
{ n: '家电', c: '#36CFC9', day: 4.3, d5: [1.8, 0.6, 2.4, 3.2, 4.3], d10: [-1.2, 0.4, 1.6, 0.8, 2.2, 1.8, 0.6, 2.4, 3.2, 4.3] , px: [2216.61, 2165.69, 2113.71, 2167.44, 2220.02, 2189.22, 2185.26, 2238.71, 2221.79, 2148.3]},
{ n: '有色', c: '#9254DE', day: 3.9, d5: [0.8, 2.2, 1.4, 2.8, 3.9], d10: [-2.2, -0.6, 0.2, 1.8, 0.6, 0.8, 2.2, 1.4, 2.8, 3.9] , px: [3675.74, 3589.64, 3542.93, 3609.14, 3597.55, 3521.76, 3585.24, 3706.1, 3671.05, 3589.1]},
{ n: '银行', c: '#2F54EB', day: 3.2, d5: [1.4, 0.8, 2.0, 1.6, 3.2], d10: [-0.8, 0.2, 1.0, 0.4, 1.8, 1.4, 0.8, 2.0, 1.6, 3.2] , px: [4861.39, 4886.19, 4776.21, 4806.75, 4876.2, 4769.25, 4695.35, 4844.85, 4952.06, 4862.7]},
{ n: '非银', c: '#F5222D', day: 2.7, d5: [0.6, 1.8, 0.2, 2.4, 2.7], d10: [-1.6, -0.4, 0.8, 0.2, 1.2, 0.6, 1.8, 0.2, 2.4, 2.7] , px: [4166.24, 4065.14, 4129.7, 4289.15, 4259.56, 4148.55, 4193.57, 4240.66, 4138.09, 4120.4]},
{ n: '传媒', c: '#FA8C16', day: 1.9, d5: [-0.4, 1.2, 0.8, 1.4, 1.9], d10: [-2.4, -1.0, -0.2, 0.6, 0.4, -0.4, 1.2, 0.8, 1.4, 1.9] , px: [1671.0, 1675.73, 1698.07, 1663.41, 1641.84, 1694.27, 1726.04, 1686.42, 1670.08, 1698.6]},
{ n: '军工', c: '#A0D911', day: 1.4, d5: [-0.6, 0.4, 1.0, 0.8, 1.4], d10: [-1.8, -1.2, -0.4, 0.2, 0.6, -0.6, 0.4, 1.0, 0.8, 1.4] , px: [2173.22, 2108.13, 2151.89, 2210.16, 2179.8, 2164.53, 2216.24, 2205.67, 2124.28, 2124.9]},
{ n: '化工', c: '#5CDBD3', day: -0.9, d5: [1.2, -0.4, -0.8, -1.2, -0.9], d10: [2.4, 1.8, 0.6, -0.2, 0.8, 1.2, -0.4, -0.8, -1.2, -0.9] , px: [3560.8, 3592.63, 3528.61, 3559.45, 3623.57, 3541.72, 3446.82, 3516.02, 3592.59, 3542.3]},
{ n: '医药', c: '#F759AB', day: -12.6, d5: [-4.2, -8.6, -6.4, -10.2, -12.6], d10: [-1.8, -3.2, -5.4, -4.2, -7.8, -4.2, -8.6, -6.4, -10.2, -12.6] , px: [2952.36, 2919.48, 2991.03, 2992.1, 2932.86, 2959.36, 2995.87, 2909.51, 2827.43, 2874.6]},
{ n: '食品饮料', c: '#FACC15', day: -18.4, d5: [-6.8, -12.4, -15.6, -10.2, -18.4], d10: [-2.4, -5.6, -8.2, -7.4, -10.8, -6.8, -12.4, -15.6, -10.2, -18.4] , px: [3686.91, 3733.93, 3611.76, 3535.15, 3589.37, 3572.26, 3484.02, 3530.21, 3628.82, 3560.2]},
{ n: '房地产', c: '#B37FEB', day: -18.5, d5: [-3.5, -7.8, -12.2, -15.6, -18.5], d10: [-1.2, -2.8, -4.6, -6.4, -5.2, -3.5, -7.8, -12.2, -15.6, -18.5] , px: [1938.05, 1970.28, 1934.11, 1908.11, 1964.89, 1985.26, 1911.34, 1874.09, 1907.61, 1892.7]}
    ] } }
  ];

  const PAGES = {
    watchlist: {
      icon: '⭐', title: '我的自选', sub: '共 12 只关注标的 · 支持自定义分组',
      blocks: [
        { t: 'addstock', d: [
          { c: '300308', faces: { fund: 78, tech: 82, flow: 74, news: 80, sent: 76  }, n: '中际旭创', sec: '通信设备', con: 'CPO · 光模块', px: '93.15', chg: '+2.41%', tur: '3.2%', lb: '1.18', alpha: 99, entry: 88, hit: 7, bg: '强势', act: '+8.6%', sel: '2026-07-21', px10: [85.1,86.4,87.8,89.2,90.5,91.3,92.0,91.6,92.4,93.15] },
          { c: '300502', faces: { fund: 72, tech: 76, flow: 70, news: 74, sent: 68  }, n: '新易盛', sec: '通信设备', con: '光模块 · 800G', px: '92.80', chg: '+1.78%', tur: '4.1%', lb: '1.35', alpha: 88, entry: 80, hit: 6, bg: '强势', act: '+11.3%', sel: '2026-07-15', px10: [84.6,85.9,87.1,88.0,89.4,90.2,91.3,92.0,92.5,92.8] },
          { c: '300394', faces: { fund: 70, tech: 72, flow: 66, news: 68, sent: 62  }, n: '天孚通信', sec: '通信设备', con: '光器件 · CPO', px: '118.64', chg: '+1.22%', tur: '2.6%', lb: '0.92', alpha: 91, entry: 78, hit: 5, bg: '强势', act: '+5.2%', sel: '2026-07-27', px10: [112.3,113.1,114.2,115.0,115.8,116.4,117.0,117.9,118.2,118.64] },
          { c: '002463', faces: { fund: 74, tech: 78, flow: 72, news: 70, sent: 66  }, n: '沪电股份', sec: '电子元件', con: 'PCB · AI 服务器', px: '41.58', chg: '+3.19%', tur: '5.8%', lb: '1.62', alpha: 95, entry: 85, hit: 6, bg: '强势', act: '+9.8%', sel: '2026-07-20', px10: [37.2,38.1,39.0,39.6,40.1,40.8,41.0,41.2,41.4,41.58] },
          { c: '002049', faces: { fund: 52, tech: 44, flow: 40, news: 46, sent: 42  }, n: '紫光国微', sec: '半导体', con: '军工芯片 · 特种 IC', px: '84.20', chg: '-0.62%', tur: '1.9%', lb: '0.88', alpha: 82, entry: 74, hit: 4, bg: '中性', act: '-2.4%', sel: '2026-07-14', px10: [86.5,86.2,85.8,85.4,85.0,84.7,84.5,84.3,84.2,84.2] },
          { c: '601138', faces: { fund: 68, tech: 62, flow: 58, news: 64, sent: 60  }, n: '工业富联', sec: '电子制造', con: 'AI 服务器 · 代工', px: '28.40', chg: '-0.94%', tur: '2.2%', lb: '1.05', alpha: 85, entry: 79, hit: 5, bg: '强势', act: '+3.5%', sel: '2026-07-29', px10: [27.1,27.3,27.6,27.9,28.0,28.2,28.3,28.4,28.35,28.4] },
          { c: '688256', faces: { fund: 76, tech: 80, flow: 78, news: 82, sent: 84  }, n: '寒武纪', sec: '半导体', con: 'AI 芯片 · 算力', px: '312.55', chg: '+5.12%', tur: '6.7%', lb: '2.10', alpha: 90, entry: 86, hit: 6, bg: '强势', act: '+21.4%', sel: '2026-07-10', px10: [268,275,283,290,296,301,305,308,310,312.55] },
          { c: '688041', faces: { fund: 66, tech: 64, flow: 60, news: 62, sent: 58  }, n: '海光信息', sec: '半导体', con: 'CPU 国产化 · 算力', px: '88.30', chg: '+2.05%', tur: '3.4%', lb: '1.27', alpha: 84, entry: 76, hit: 4, bg: '中性', act: '+6.1%', sel: '2026-07-23', px10: [83.5,84.2,85.0,85.8,86.5,87.2,87.8,88.0,88.2,88.3] },
          { c: '603019', faces: { fund: 58, tech: 56, flow: 54, news: 55, sent: 52  }, n: '中科曙光', sec: '计算机', con: '算力 · 信创', px: '55.20', chg: '+1.05%', tur: '2.8%', lb: '1.12', alpha: 80, entry: 71, hit: 4, bg: '中性', act: '+4.2%', sel: '2026-07-30', px10: [53.0,53.4,53.8,54.2,54.5,54.8,55.0,55.1,55.15,55.2] },
          { c: '688008', faces: { fund: 50, tech: 48, flow: 44, news: 46, sent: 45  }, n: '澜起科技', sec: '半导体', con: '存储芯片 · 内存接口', px: '45.20', chg: '+0.00%', tur: '2.1%', lb: '0.96', alpha: 78, entry: 69, hit: 3, bg: '中性', act: '-1.8%', sel: '2026-07-16', px10: [46.0,45.8,45.6,45.5,45.4,45.3,45.2,45.2,45.2,45.2] },
          { c: '000063', faces: { fund: 55, tech: 54, flow: 52, news: 53, sent: 51  }, n: '中兴通讯', sec: '通信设备', con: '5G · 算力网络', px: '36.20', chg: '+0.62%', tur: '1.8%', lb: '1.02', alpha: 76, entry: 68, hit: 3, bg: '中性', act: '+2.6%', sel: '2026-08-01', px10: [35.4,35.6,35.8,35.9,36.0,36.1,36.1,36.2,36.2,36.2] },
          { c: '300750', faces: { fund: 72, tech: 68, flow: 70, news: 66, sent: 64  }, n: '宁德时代', sec: '电池', con: '动力电池 · 储能', px: '218.40', chg: '+1.36%', tur: '1.5%', lb: '0.85', alpha: 86, entry: 81, hit: 5, bg: '强势', act: '+7.4%', sel: '2026-07-24', px10: [210,212,214,215,216,217,218,218.1,218.3,218.4] },
          { c: '002594', faces: { fund: 66, tech: 62, flow: 60, news: 61, sent: 58  }, n: '比亚迪', sec: '汽车', con: '新能源车 · 出海', px: '245.30', chg: '+0.88%', tur: '2.4%', lb: '1.31', alpha: 83, entry: 75, hit: 4, bg: '中性', act: '+5.9%', sel: '2026-07-28', px10: [238,239,240,241,242,243,244,244.8,245.1,245.3] },
          { c: '600519', faces: { fund: 45, tech: 42, flow: 38, news: 40, sent: 36  }, n: '贵州茅台', sec: '白酒', con: '白酒 · 消费白马', px: '1480.00', chg: '-0.22%', tur: '0.4%', lb: '0.72', alpha: 72, entry: 64, hit: 2, bg: '弱势', act: '-3.6%', sel: '2026-07-09', px10: [1505,1500,1498,1493,1490,1488,1485,1483,1481,1480] },
          { c: '601318', faces: { fund: 48, tech: 46, flow: 44, news: 42, sent: 40  }, n: '中国平安', sec: '保险', con: '保险 · 金融权重', px: '55.10', chg: '+0.35%', tur: '0.9%', lb: '0.88', alpha: 70, entry: 62, hit: 2, bg: '中性', act: '-1.2%', sel: '2026-07-17', px10: [55.9,55.8,55.6,55.5,55.4,55.3,55.2,55.15,55.12,55.1] },
          { c: '600900', faces: { fund: 56, tech: 52, flow: 55, news: 50, sent: 54  }, n: '长江电力', sec: '电力', con: '电力 · 高股息', px: '27.80', chg: '+0.18%', tur: '0.6%', lb: '0.91', alpha: 74, entry: 66, hit: 3, bg: '中性', act: '+1.8%', sel: '2026-07-31', px10: [27.4,27.45,27.5,27.55,27.6,27.65,27.7,27.75,27.78,27.8] }
        ] },
        { t: 'table', d: { head: ['代码', '名称', '现价', '涨跌幅', '换手率', '量比', '板块', '概念', 'Alpha Score', 'Entry Score', 'Strategy Hit', '市场背景', '趋势预测(1月)', '实际涨跌', '入选日', '操作'], rows: [] } }
      ]
    },
    radar: {
      icon: '📡', title: 'Alpha 雷达', sub: '每日动态选股 · 多因子 Alpha 打分 · 更新时间 08:30',
      blocks: [
        { t: 'kpis', d: [
          { t: '候选池', v: '16', d: '只跟踪标的', cls: '', icon: '🎯' },
          { t: '今日入选', v: '5', d: 'Top 5 组合', cls: '', icon: '📋' },
          { t: '组合 Alpha', v: '+18.6%', d: '年化超额(近一年回测)', cls: 'up', icon: '⚡' },
          { t: '胜率', v: '72.4%', d: '历史信号命中率', cls: '', icon: '🏆' }
        ] },
        { t: 'bars', d: [
          { name: '动量因子', val: 88, txt: '0.88', color: '#FF4D4F' },
          { name: '估值因子', val: 61, txt: '0.61', color: '#2962FF' },
          { name: '盈利质量', val: 74, txt: '0.74', color: '#722ED1' },
          { name: '资金流向', val: 92, txt: '0.92', color: '#FF9800' },
          { name: '事件驱动', val: 57, txt: '0.57', color: '#13C2C2' },
          { name: '波动率', val: 43, txt: '0.43', color: '#52C41A' }
        ] },
        { t: 'note', d: 'Alpha 分数 = 五维因子加权(动量 25% / 资金 20% / 盈利 20% / 估值 20% / 事件 15%),每日 08:30 按日期种子重算,自动选出得分最高的 5 只进入今日组合。' }
      ]
    },
    info: {
      icon: '🔍', title: '股票情报', sub: '全市场情报聚合 · 关键词检索',
      blocks: [
        { t: 'intel', d: { title: '个股综合研判' } }
      ]
    },
    announce: {
      icon: '📢', title: '公告中心', sub: '今日 08-08 · 沪深两市公告流',
      blocks: [
        { t: 'kpis', d: [
          { t: '今日公告', v: '2,318', d: '篇', cls: '', icon: '📄' },
          { t: '重大事项', v: '47', d: '含停牌/重组/定增', cls: 'warn', icon: '⚠️' },
          { t: '业绩预告', v: '86', d: 'Q2 预告窗口', cls: '', icon: '📊' },
          { t: '股东增减持', v: '29', d: '其中减持 21', cls: '', icon: '🔄' }
        ] },
        { t: 'list', d: [
          { t: '中际旭创:2026 年半年度报告', sub: '归母净利 68.4 亿(+82.6%),大超一致预期', tag: '业绩', cls: 'up', time: '16:30' },
          { t: '寒武纪:关于签订重大合同的公告', sub: '算力租赁合同总金额约 12.8 亿元', tag: '重大合同', cls: 'blue', time: '15:02' },
          { t: '澜起科技:首次公开发行股票上市公告', sub: '将于 08-15 登陆科创板,发行价 45.20 元', tag: 'IPO', cls: 'warn', time: '14:40' },
          { t: '沪电股份:关于股份回购进展的公告', sub: '累计回购 1,820 万股,占总股本 0.95%', tag: '回购', cls: 'blue', time: '13:18' },
          { t: '海光信息:股东减持计划公告', sub: '红杉拟减持不超过总股本 1.2%', tag: '减持', cls: 'down', time: '11:06' }
        ] }
      ]
    },
    analysis: {
      icon: '📈', title: '行情分析', sub: '中际旭创 300308 · 日 K + 技术指标',
      blocks: [
        { t: 'kpis', d: [
          { t: '最新价', v: '93.15', d: '+2.19 (+2.41%)', cls: 'up', icon: '💰' },
          { t: '成交量', v: '4.86 万手', d: '量比 1.18', cls: '', icon: '📊' },
          { t: '换手率', v: '3.21%', d: '自由流通市值 2,898 亿', cls: '', icon: '🔄' },
          { t: '振幅', v: '3.86%', d: '区间:90.06 ~ 93.55', cls: '', icon: '📉' }
        ] },
        { t: 'spark', d: { title: '60 分钟分时', pts: [78, 79.2, 80.5, 79.8, 82, 83.5, 82.8, 85, 84.2, 86.5, 87.8, 87.2, 89, 90.2, 89.6, 91, 92.3, 93.15], color: '#FF4D4F' } },
        { t: 'grid', d: [
          { icon: '📐', t: 'MA 均线', sub: 'MA5 90.12 / MA20 85.44 / MA60 78.93 · 多头排列', tag: '偏多', cls: 'up' },
          { icon: '📏', t: 'MACD', sub: 'DIF 3.21 / DEA 2.48,红柱放大', tag: '金叉', cls: 'up' },
          { icon: '🌡️', t: 'RSI(14)', sub: 'RSI 68.2,接近超买但未钝化', tag: '强势', cls: 'warn' },
          { icon: '🎯', t: '布林带', sub: '股价贴上轨 92.88,开口向上', tag: '强势', cls: 'up' },
          { icon: '💧', t: 'KDJ', sub: 'K 82 / D 74 / J 98,高位钝化', tag: '过热', cls: 'down' },
          { icon: '⚖️', t: 'OBV', sub: '能量潮创新高,量价配合良好', tag: '健康', cls: 'up' }
        ] }
      ]
    },
    factors: {
      icon: '🧮', title: '因子计算', sub: 'A 股因子库 · 覆盖 5,800+ 标的 · 最新截面 08-08',
      blocks: [
        { t: 'kpis', d: [
          { t: '因子总数', v: '42', d: '个有效因子', cls: '', icon: '🧬' },
          { t: 'IC 均值', v: '0.038', d: '月频 RankIC', cls: '', icon: '📈' },
          { t: 'ICIR', v: '0.31', d: '因子稳健度', cls: '', icon: '🛡️' },
          { t: '换手率', v: '28%', d: '月均单边', cls: '', icon: '🔄' }
        ] },
        { t: 'table', d: { head: ['因子', '类别', 'IC', 'ICIR', '方向', '状态'], rows: [
          ['1 月动量', '动量', '0.062', '0.48', '正向', '<span class="up">有效</span>'],
          ['3 月反转', '动量', '-0.041', '0.35', '负向', '<span class="up">有效</span>'],
          ['EP(盈利收益率)', '估值', '0.055', '0.42', '正向', '<span class="up">有效</span>'],
          ['营收同比', '盈利', '0.048', '0.29', '正向', '<span class="up">有效</span>'],
          ['北向净流入', '资金', '0.071', '0.52', '正向', '<span class="up">有效</span>'],
          ['波动率(60日)', '风险', '-0.018', '0.12', '负向', '<span class="down">失效</span>'],
          ['换手率乖离', '流动性', '0.012', '0.09', '正向', '<span class="down">失效</span>']
        ] } }
      ]
    },
    lab: {
      icon: '🎯', title: '策略实验室', sub: '已保存策略 5 个 · 支持回测与实盘信号',
      blocks: [
        { t: 'grid', d: [
          { icon: '🚀', t: '动量突破 T+5', sub: '20日新高 + 量比>1.5,持有 5 日', tag: '年化 +42%', cls: 'up' },
          { icon: '💎', t: '低估值修复', sub: 'PE 分位 <20% + 营收加速', tag: '年化 +28%', cls: 'up' },
          { icon: '🤖', t: 'AI 情绪共振', sub: '研报情绪 + 资金流 + 事件日历', tag: '年化 +35%', cls: 'up' },
          { icon: '🧊', t: '红利防守', sub: '股息率 >5% + 低波动', tag: '年化 +15%', cls: 'blue' },
          { icon: '⚡', t: '事件驱动套利', sub: '并购重组 / 定增折价 / 解禁错杀', tag: '年化 +51%', cls: 'up' }
        ] },
        { t: 'table', d: { head: ['策略', '最近信号', '持有收益', '胜率', '回撤'], rows: [
          ['动量突破 T+5', '中际旭创 08-05', '+6.2%', '78%', '-8.4%'],
          ['AI 情绪共振', '新易盛 08-03', '+4.8%', '74%', '-11.2%'],
          ['事件驱动套利', '寒武纪 07-28', '+12.1%', '66%', '-15.6%']
        ] } }
      ]
    },
    backtest: {
      icon: '📉', title: '回测系统', sub: '策略「动量突破 T+5」 · 回测区间 2025-01-01 ~ 2026-08-08',
      blocks: [
        { t: 'kpis', d: [
          { t: '累计收益', v: '+86.4%', d: '基准沪深300 +21.3%', cls: 'up', icon: '🏆' },
          { t: '年化收益', v: '+42.1%', d: 'Sharpe 1.86', cls: 'up', icon: '⚡' },
          { t: '最大回撤', v: '-8.42%', d: '发生在 2026-02', cls: 'down', icon: '🕳️' },
          { t: '胜率', v: '77.8%', d: '共 138 笔交易', cls: '', icon: '🎯' }
        ] },
        { t: 'spark', d: { title: '策略净值曲线(绿=基准)', pts: [1, 1.02, 1.01, 1.05, 1.08, 1.06, 1.12, 1.15, 1.12, 1.2, 1.24, 1.22, 1.3, 1.34, 1.31, 1.42, 1.48, 1.52, 1.5, 1.62, 1.7, 1.86], color: '#FF4D4F' } },
        { t: 'table', d: { head: ['区间', '收益', '回撤', '交易数', '结论'], rows: [
          ['2025 Q1', '+8.2%', '-3.1%', '31', '<span class="up">有效</span>'],
          ['2025 Q2', '+15.4%', '-4.6%', '38', '<span class="up">有效</span>'],
          ['2025 Q3', '-2.1%', '-5.8%', '24', '<span class="down">失效</span>'],
          ['2025 Q4', '+18.9%', '-3.2%', '29', '<span class="up">有效</span>'],
          ['2026 Q1', '+21.6%', '-8.4%', '16', '<span class="up">有效</span>'],
          ['2026 Q2', '+24.2%', '-4.1%', '28', '<span class="up">有效</span>']
        ] } }
      ]
    },
    events: {
      icon: '⚡', title: '事件驱动', sub: '宏观日历 + 公司事件 · 未来 60 天',
      blocks: [
        { t: 'list', d: [
          { t: '08-12 · 美国 7 月 CPI', sub: '预期 3.0% yoy,核心 CPI 3.2% — 美联储 9 月议息前瞻', tag: '宏观', cls: 'warn', time: '4 天后' },
          { t: '08-13 · 中国 7 月社融/信贷', sub: '社融增量一致预期 1.1 万亿,关注企业中长贷', tag: '宏观', cls: 'warn', time: '5 天后' },
          { t: '08-15 · 澜起科技科创板上市', sub: '发行价 45.20 元,募资 62 亿,关注打新与首日表现', tag: 'IPO', cls: 'blue', time: '7 天后' },
          { t: '08-18 · 中际旭创中报披露', sub: '一致预期归母净利 68 亿(+82%),关注毛利率与 1.6T 进度', tag: '业绩', cls: 'up', time: '10 天后' },
          { t: '08-20 · 中国 8 月 LPR 报价', sub: '市场预期维持不变,关注 MLF 续作', tag: '宏观', cls: 'warn', time: '12 天后' },
          { t: '08-26 · 英伟达 Q2 财报', sub: '数据中心收入指引是 CPO/光模块板块关键变量', tag: '海外', cls: 'up', time: '18 天后' },
          { t: '08-31 · 8 月制造业 PMI', sub: '7 月 49.4,关注重回荣枯线', tag: '宏观', cls: 'warn', time: '23 天后' }
        ] }
      ]
    },
    portfolio: {
      icon: '💼', title: '投资组合', sub: '总资产 3,286,540 元 · 今日盈亏 +18,245 (+0.56%)',
      blocks: [
        { t: 'kpis', d: [
          { t: '总资产', v: '328.65 万', d: '较昨日 +0.56%', cls: 'up', icon: '💰' },
          { t: '累计收益', v: '+68.4 万', d: '年化 +26.2%', cls: 'up', icon: '🏆' },
          { t: '仓位', v: '82.6%', d: '现金 57.2 万', cls: '', icon: '⚖️' },
          { t: '今日盈亏', v: '+18,245', d: '跑赢沪深300 +0.4%', cls: 'up', icon: '📈' }
        ] },
        { t: 'table', d: { head: ['股票', '持仓', '成本', '现价', '市值', '盈亏'], rows: [
          ['中际旭创', '12,000 股', '71.20', '93.15', '111.78 万', '<span class="up">+30.8%</span>'],
          ['新易盛', '8,000 股', '78.50', '92.80', '74.24 万', '<span class="up">+18.2%</span>'],
          ['寒武纪', '1,200 股', '268.00', '312.55', '37.51 万', '<span class="up">+16.6%</span>'],
          ['紫光国微', '5,000 股', '89.90', '84.20', '42.10 万', '<span class="down">-6.3%</span>'],
          ['现金', '—', '—', '—', '57.20 万', '—']
        ] } },
        { t: 'bars', d: [
          { name: '通信设备', val: 72, txt: '36.8%', color: '#FF4D4F' },
          { name: '半导体', val: 38, txt: '19.2%', color: '#722ED1' },
          { name: '消费电子', val: 30, txt: '15.4%', color: '#2962FF' },
          { name: '军工电子', val: 22, txt: '11.2%', color: '#13C2C2' },
          { name: '现金', val: 34, txt: '17.4%', color: '#8C8C8C' }
        ] }
      ]
    },
    ai: {
      icon: '🤖', title: 'AI 研究', sub: '多模态研究助手 · 支持个股/行业/策略问答',
      blocks: [
        { t: 'chat', d: [
          { role: 'u', text: '帮我分析中际旭创中报前的交易窗口,以及风险点' },
          { role: 'a', text: '基于一致预期与事件日历,给出以下观点:1) 8/18 中报为关键催化,预期净利 68 亿(+82%),毛利率能否维持 33%+ 是分歧点;2) 1.6T 光模块 Q4 放量节奏决定明年估值中枢;3) 风险:北向资金已连续两周净卖出光模块,若 CPI 超预期引发科技股回调,建议在 89 元以下分批建仓,止损 84 元。' }
        ] },
        { t: 'list', d: [
          { t: '📄 券商研报 · 中际旭创', sub: '目标价均值 148.2 元,最高 165 元,评级分布 买入 38 / 增持 12', tag: '一致预期', cls: 'up', time: '今日' },
          { t: '📊 AI 因子扫描', sub: '在今日 5 只入选股中,资金流因子贡献 Alpha 最大(权重 20%)', tag: '雷达', cls: 'blue', time: '08:30' },
          { t: '🗓️ 事件提醒', sub: '中报 8/18 前 5 日历史统计:光模块龙头平均上涨 +4.8%', tag: '历史统计', cls: 'warn', time: '本周' }
        ] }
      ]
    },
    sim: {
      icon: '🔄', title: '模拟交易', sub: '虚拟资金 100 万 · 支持 T+1 与两融模拟',
      blocks: [
        { t: 'panel', d: { title: '买入委托', fields: [
          { k: '股票代码', v: '300308 中际旭创' },
          { k: '委托价格', v: '93.15(限价)' },
          { k: '委托数量', v: '10,000 股 = 93.15 万' }
        ], btn: '提交委托' } },
        { t: 'kpis', d: [
          { t: '模拟资产', v: '112.6 万', d: '今日 +1.2 万', cls: 'up', icon: '💰' },
          { t: '可用资金', v: '19.4 万', d: '持仓市值 93.2 万', cls: '', icon: '💳' },
          { t: '委托成功率', v: '96.4%', d: '滑点控制 0.1%', cls: '', icon: '✅' }
        ] },
        { t: 'table', d: { head: ['时间', '方向', '股票', '价格', '数量', '状态'], rows: [
          ['08-08 14:32', '<span class="up">买入</span>', '中际旭创', '92.80', '10,000', '<span class="up">已成交</span>'],
          ['08-07 10:05', '<span class="up">买入</span>', '新易盛', '90.40', '5,000', '<span class="up">已成交</span>'],
          ['08-06 13:20', '<span class="down">卖出</span>', '天孚通信', '115.20', '2,000', '<span class="up">已成交</span>'],
          ['08-05 09:41', '<span class="up">买入</span>', '寒武纪', '305.00', '800', '排队中']
        ] } }
      ]
    },
    risk: {
      icon: '🛡️', title: '风险监控', sub: '组合风险实时评估 · 最新扫描 15:00',
      blocks: [
        { t: 'kpis', d: [
          { t: '组合风险分', v: '62', d: '中等偏高', cls: 'warn', icon: '🌡️' },
          { t: '最大回撤(近30日)', v: '-6.8%', d: '阈值 -10%', cls: '', icon: '🕳️' },
          { t: '集中度', v: '71.2%', d: '前 3 大持仓占比,超阈值 70%', cls: 'warn', icon: '🎯' },
          { t: '波动率(年化)', v: '28.4%', d: '高于基准 6.2pp', cls: '', icon: '📊' }
        ] },
        { t: 'list', d: [
          { t: '⚠️ 集中度超限', sub: '通信设备板块占比 36.8%,建议降至 30% 以下以控制回撤', tag: '警告', cls: 'warn', time: '15:00' },
          { t: '🔔 紫光国微跌破成本', sub: '浮亏 -6.3%,已触发 -5% 提醒线,建议关注支撑位 82.5', tag: '提示', cls: 'blue', time: '14:21' },
          { t: '✅ 杠杆水平正常', sub: '当前无两融持仓,杠杆率 0%', tag: '正常', cls: 'up', time: '15:00' },
          { t: '✅ 流动性充裕', sub: '现金占比 17.4%,可满足 3 个交易日极端赎回', tag: '正常', cls: 'up', time: '15:00' }
        ] }
      ]
    },
    positions: {
      icon: '📒', title: '持仓明细', sub: '5 个持仓 · 合并市值 271.4 万',
      blocks: [
        { t: 'table', d: { head: ['代码', '名称', '持仓', '成本', '现价', '市值', '盈亏', '占比', '操作'], rows: [
          ['300308', '中际旭创', '12,000', '71.20', '93.15', '111.8 万', '<span class="up">+30.8%</span>', '34.4%', '买/卖'],
          ['300502', '新易盛', '8,000', '78.50', '92.80', '74.2 万', '<span class="up">+18.2%</span>', '22.8%', '买/卖'],
          ['688256', '寒武纪', '1,200', '268.00', '312.55', '37.5 万', '<span class="up">+16.6%</span>', '11.6%', '买/卖'],
          ['002049', '紫光国微', '5,000', '89.90', '84.20', '42.1 万', '<span class="down">-6.3%</span>', '13.0%', '买/卖'],
          ['601138', '工业富联', '2,000', '29.40', '28.40', '5.7 万', '<span class="down">-3.4%</span>', '1.7%', '买/卖']
        ] } }
      ]
    },
    calendar: {
      icon: '📅', title: '日历', sub: '2026 年 8 月 · 交易事件标记',
      blocks: [
        { t: 'calendar', d: { year: 2026, month: 7, marks: { 8: 'CPI', 12: 'FOMC', 15: '澜起IPO', 18: '中际旭创中报', 20: 'LPR', 26: '英伟达财报', 31: 'PMI' } } },
        { t: 'list', d: [
          { t: '08-18 · 中际旭创中报', sub: '一致预期净利 68 亿(+82%),1.6T 进度为焦点', tag: '重要', cls: 'warn', time: '10 天后' },
          { t: '08-26 · 英伟达 Q2 财报', sub: '数据中心指引影响光模块板块', tag: '海外', cls: 'up', time: '18 天后' }
        ] }
      ]
    },
    reports: {
      icon: '📄', title: '报告', sub: '深度研报与周报库 · 共 128 份',
      blocks: [
        { t: 'list', d: [
          { t: '📕 光模块产业链 2026 下半年展望', sub: '1.6T 放量节奏 · 硅光 vs 可插拔之争 · 24 页', tag: '深度', cls: 'up', time: '08-06' },
          { t: '📗 半导体设备国产化进度跟踪', sub: '刻蚀/薄膜/量测环节国产化率全景 · 18 页', tag: '深度', cls: 'up', time: '08-02' },
          { t: '📘 周报 · 第 32 周(08-02 ~ 08-08)', sub: '组合本周 +3.2%,超额 1.1%', tag: '周报', cls: 'blue', time: '08-08' },
          { t: '📙 AI 算力资本开支追踪', sub: '北美云厂 2026 CAPEX 合计上修至 3,800 亿美元', tag: '专题', cls: 'warn', time: '07-28' },
          { t: '📕 月度组合调仓报告 · 7 月', sub: '7 月收益 +8.6%,调仓 3 笔', tag: '月报', cls: 'blue', time: '07-31' }
        ] },
        { t: 'kpis', d: [
          { t: '深度报告', v: '36', d: '篇 · 平均 22 页', cls: '', icon: '📕' },
          { t: '周报', v: '52', d: '篇 · 每周五更新', cls: '', icon: '📘' },
          { t: '行业专题', v: '28', d: '篇 · 覆盖 14 个行业', cls: '', icon: '📙' }
        ] }
      ]
    },
    messages: {
      icon: '🔔', title: '消息中心', sub: '3 条未读 · 重要消息会置顶高亮',
      blocks: [
        { t: 'list', d: [
          { t: '🔴 风险提醒 · 紫光国微浮亏达 -6.3%', sub: '已跌破 -5% 提醒线,系统建议评估持仓逻辑是否变化', tag: '未读', cls: 'warn', time: '14:21' },
          { t: '🔴 Alpha 雷达选股完成', sub: '今日 5 只入选:中际旭创/沪电股份/天孚通信/寒武纪/新易盛', tag: '未读', cls: 'blue', time: '08:30' },
          { t: '🟡 中报日历提醒 · 中际旭创 8/18', sub: '持仓股中报临近,历史上前 5 日平均 +4.8%', tag: '未读', cls: 'blue', time: '08:01' },
          { t: '⚪ 周报已生成', sub: '第 32 周组合周报已发布,点击查看', tag: '已读', cls: '', time: '08-08' },
          { t: '⚪ 策略信号 · 动量突破', sub: '中际旭创触发买入信号(08-05 收盘)', tag: '已读', cls: '', time: '08-05' }
        ] }
      ]
    },
    settings: {
      icon: '⚙️', title: '设置', sub: '偏好与系统配置',
      blocks: [
        { t: 'grid', d: [
          { icon: '🎨', t: '界面主题', sub: '深色 · 红涨绿跌 · 字体 13px', tag: '深色', cls: 'blue' },
          { icon: '🔔', t: '推送设置', sub: '信号推送 / 风险提醒 / 日历提醒', tag: '已开启', cls: 'up' },
          { icon: '📡', t: '数据源', sub: 'Level-2 行情 · 实时 · 延迟 0.2s', tag: '专业版', cls: 'up' },
          { icon: '🤖', t: 'AI 引擎', sub: 'GLM-4 系列 · 因子计算深度', tag: 'Pro', cls: 'blue' },
          { icon: '🔐', t: '安全', sub: '两步验证已开启 · 设备 2 台', tag: '安全', cls: 'up' },
          { icon: '💳', t: '账户', sub: 'Lucci · 专业版 · 到期 2027-03', tag: '有效', cls: 'up' }
        ] }
      ]
    }
  };

  // ---------- 渲染块 ----------
  function renderBlock(b) {
    switch (b.t) {
      case 'kpis': return kpis(b.d);
      case 'table': return table(b.d.head, b.d.rows);
      case 'bars': return bars(b.d);
      case 'flowchart': {
        const legend = b.d.groups.map(g => '<span><i style="background:' + g.c + '"></i>' + g.n + '</span>').join('');
        return '<div class="pg-panel"><div class="pg-panel-t"><span>📊 ' + b.d.title + '</span>' +
          '<span class="pg-flow-tabs"><span class="pg-flow-tab active" data-mode="day">当日</span>' +
          '<span class="pg-flow-tab" data-mode="d5">近5日</span>' +
          '<span class="pg-flow-tab" data-mode="d10">近10日</span></span></div>' +
          '<div class="pg-flow"><div class="pg-flow-body"></div><div class="pg-flow-legend">' + legend + '</div></div></div>';
      }
      case 'list': return list(b.d);
      case 'grid': return grid(b.d);
      case 'spark': return '<div class="pg-panel"><div class="pg-panel-t">' + b.d.title + '</div>' + sparkline(b.d.pts, 560, 120, b.d.color) + '</div>';
      case 'addstock': return '<div class="pg-panel"><div class="pg-panel-t">➕ 新增个股</div>' +
        '<div class="as-search"><input id="asInput" placeholder="输入代码 / 名称,回车或点添加,如 300308 或 中际旭创" spellcheck="false"><button id="asAddBtn">添加</button></div>' +
        '<div class="as-msg" id="asMsg"></div></div>';
      case 'note': return '<div class="pg-note">' + b.d + '</div>';
      case 'search': return '<div class="pg-search"><span>🔎</span><input placeholder="' + b.d + '"><button>搜索</button></div>';
      case 'intel': return '<div class="pg-panel"><div class="pg-panel-t">🧭 ' + b.d.title + '</div>' +
        '<div class="intel-search"><input id="intelInput" placeholder="输入代码 / 名称,如 300308 或 中际旭创" spellcheck="false"><button id="intelBtn">综合研判</button></div>' +
        '<div class="intel-body" id="intelBody"><div class="intel-empty">输入股票代码或名称,生成 5 面评分 · 机构动向 · 研报 · 新闻综合研判</div></div></div>';
      case 'chat': return '<div class="pg-chat">' + b.d.map(m =>
        '<div class="msg ' + m.role + '"><span class="msg-ic">' + (m.role === 'u' ? '🧑' : '🤖') + '</span><div class="msg-b">' + m.text + '</div></div>'
      ).join('') + '</div>';
      case 'panel': return '<div class="pg-panel"><div class="pg-panel-t">' + b.d.title + '</div>' + b.d.fields.map(f =>
        '<div class="pg-field"><span class="pg-field-k">' + f.k + '</span><span class="pg-field-v">' + f.v + '</span></div>'
      ).join('') + '<div class="pg-panel-btn">' + b.d.btn + '</div></div>';
      case 'cards': return '<div class="pg-cards">' + b.d.map(c =>
        '<div class="pg-card" style="border-top:2px solid ' + c.color + '"><div class="pg-card-t">' + c.title + '</div><div class="pg-card-v">' + c.val + '</div><div class="pg-card-n">' + c.note + '</div></div>'
      ).join('') + '</div>';
      case 'index': {
        const it = b.d.items;
        const cards = it.map((x, i) =>
          '<div class="ich-card"><div class="ich-cn">' + x.n + '</div>' +
          '<div class="ich-cv ' + (x.chg.charAt(0) === '-' ? 'down' : 'up') + '">' + x.v + '</div>' +
          '<div class="ich-cd ' + (x.chg.charAt(0) === '-' ? 'down' : 'up') + '">' + x.chg + '  ' + x.pct + '</div>' +
          '<div class="ich-ex">' + x.extra + '</div>' +
          '<div class="ich-cs">' + sparkline(x.px, 100, 26, x.c) + '</div></div>'
        ).join('');
        return '<div class="pg-panel"><div class="pg-panel-t">' + b.d.title + '</div>' +
          '<div class="ich-cards">' + cards + '</div></div>';
      }
      case 'calendar': {
        const { year, month, marks } = b.d;
        const first = new Date(year, month, 1).getDay();
        const days = new Date(year, month + 1, 0).getDate();
        let cells = '<span class="cdow">日</span><span class="cdow">一</span><span class="cdow">二</span><span class="cdow">三</span><span class="cdow">四</span><span class="cdow">五</span><span class="cdow">六</span>';
        for (let i = 0; i < first; i++) cells += '<span class="cd-null"></span>';
        for (let d = 1; d <= days; d++) {
          const m = marks[d];
          cells += '<div class="cd ' + (m ? 'cd-mark' : '') + (d === 18 ? ' cd-today' : '') + '"><span class="cd-d">' + d + '</span>' + (m ? '<span class="cd-m">' + m + '</span>' : '') + '</div>';
        }
        return '<div class="pg-panel"><div class="pg-panel-t">2026 年 8 月 · 事件日历</div><div class="pg-calendar">' + cells + '</div></div>';
      }
    }
    return '';
  }

  function renderPage(id) {
    const cfg = PAGES[id];
    if (!cfg) return;
    let holder = document.getElementById('page-' + id);
    if (!holder) {
      holder = document.createElement('div');
      holder.className = 'page';
      holder.id = 'page-' + id;
      document.querySelector('.content').appendChild(holder);
    }
    holder.innerHTML =
      '<div class="pg-head"><div class="pg-title"><span class="pg-icon">' + cfg.icon + '</span><div><div class="pg-h1">' + cfg.title + '</div><div class="pg-h2">' + cfg.sub + '</div></div></div>' +
      '<div class="pg-actions"><span class="pg-act-btn">⟳ 刷新</span><span class="pg-act-btn primary">导出</span></div></div>' +
      cfg.blocks.map(renderBlock).join('');
  }

  // ---------- 导航切换 ----------
  function switchPage(id) {
    document.querySelectorAll('.content > .page').forEach(p => { p.style.display = 'none'; });
    const target = document.getElementById('page-' + id);
    if (target) target.style.display = 'flex';
    document.querySelectorAll('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.page === id));
    const sc = document.querySelector('.content');
    if (sc) sc.scrollTop = 0;
  }

  // ---------- 初始化 ----------
  document.addEventListener('DOMContentLoaded', () => {
    Object.keys(PAGES).forEach(renderPage);
    const mkt = document.getElementById('mkt-indices');
    if (mkt) mkt.innerHTML = INDEX_BLOCKS.map(renderBlock).join('');
    const moved = document.getElementById('moved-radar');
    const radar = document.getElementById('page-radar');
    if (moved && radar) { radar.appendChild(moved); moved.style.display = ''; }

    // ---------- 板块资金流向图 ----------
    function flowTA(px) {
      const cur = px[px.length - 1];
      const H = Math.max.apply(null, px), L = Math.min.apply(null, px);
      const ma5 = px.slice(-5).reduce((a, b) => a + b, 0) / 5;
      const ma10 = px.reduce((a, b) => a + b, 0) / 10;
      const sup = Math.min(L, ma5), res = Math.max(H, ma5);
      const tag = cur > ma5 && ma5 > ma10 ? '偏多' : (cur < ma5 && ma5 < ma10 ? '偏空' : '震荡');
      return {
        cur: cur.toFixed(2), sup: sup.toFixed(2), res: res.toFixed(2),
        dSup: ((cur - sup) / cur * 100).toFixed(1), dRes: ((res - cur) / cur * 100).toFixed(1), tag
      };
    }
    function buildFlow(bodyEl, block, mode) {
      const gs = block.d.groups;
      const valOf = g => mode === 'day' ? g.day :
        (mode === 'd5' ? g.d5.reduce((a, b) => a + b, 0) : g.d10.reduce((a, b) => a + b, 0));
      const maxAbs = Math.max.apply(null, gs.map(g => Math.abs(valOf(g))));
      const note = mode === 'day' ? '' :
        '<div class="ff-note">' + (mode === 'd5' ? '近 5 日' : '近 10 日') + '累计主力净流入(亿元)</div>';
      bodyEl.innerHTML = note + '<div class="ff-day">' + gs.map(g => {
        const v = valOf(g);
        const w = Math.max(Math.abs(v) / maxAbs * 44, 1.5);
        const up = v >= 0;
        const ta = flowTA(g.px);
        const tcls = ta.tag === '偏多' ? 'up' : (ta.tag === '偏空' ? 'down' : 'mid');
        return '<div class="ff-group">' +
          '<div class="ff-row"><span class="ff-name">' + g.n + '</span>' +
          '<div class="ff-track"><div class="ff-zero"></div>' +
          '<div class="ff-fill ' + (up ? 'up' : 'down') + '" style="left:' + (up ? '50%' : (50 - w).toFixed(2) + '%') + ';width:' + w.toFixed(2) + '%"></div></div>' +
          '<span class="ff-val ' + (up ? 'up' : 'down') + '">' + (up ? '+' : '') + v.toFixed(1) + ' 亿</span></div>' +
          '<div class="ff-sub">' +
          '<span class="fs-cur">现价 ' + ta.cur + '</span>' +
          '<span>支撑 <b>' + ta.sup + '</b></span>' +
          '<span>压力 <b>' + ta.res + '</b></span>' +
          '<span class="fs-gap">距支撑 ' + ta.dSup + '% · 距压力 ' + ta.dRes + '%</span>' +
          '<span class="fs-tag ' + tcls + '">' + ta.tag + '</span>' +
          '</div></div>';
      }).join('') + '</div>';
    }
    document.querySelectorAll('.pg-flow').forEach(fc => {
      const pageId = fc.closest('.page').id.replace('page-', '');
      const page = PAGES[pageId];
      let block = page ? page.blocks.find(b => b.t === 'flowchart') : null;
      if (!block && pageId === 'market') block = INDEX_BLOCKS.find(b => b.t === 'flowchart');
      if (block) buildFlow(fc.querySelector('.pg-flow-body'), block, 'day');
    });

    // ---------- 新增个股模块 ----------
    const CAND = PAGES.watchlist.blocks[0].d;
    const LS_KEY = 'aros_watchlist_v1';

    function setMsg(html, ok) {
      const m = document.getElementById('asMsg');
      if (m) { m.innerHTML = html; m.className = 'as-msg ' + (ok ? 'ok' : 'err'); }
    }
    function getCodes() {
      try {
        const s = localStorage.getItem(LS_KEY);
        if (s) {
          const a = JSON.parse(s);
          if (Array.isArray(a) && a.length) return a.filter(c => CAND.some(x => x.c === c));
        }
      } catch (e) {}
      return CAND.slice(0, 8).map(x => x.c);
    }
    function saveCodes(codes) {
      try { localStorage.setItem(LS_KEY, JSON.stringify(codes)); } catch (e) {}
    }
    const FACE_W = { fund: 0.30, tech: 0.25, flow: 0.20, news: 0.15, sent: 0.10 };
    function faceScore(s) {
      const faces = s.faces || { fund: 50, tech: 50, flow: 50, news: 50, sent: 50 };
      return Object.keys(FACE_W).reduce((a, k) => a + FACE_W[k] * faces[k], 0);
    }
    function kTechScore(s) {
      const px = s.px10;
      if (!px || px.length < 3) return 50;
      const cur = px[px.length - 1];
      const mom = (cur - px[0]) / px[0] * 100;
      const ma5 = px.slice(-5).reduce((a, b) => a + b, 0) / 5;
      const ma10 = px.reduce((a, b) => a + b, 0) / px.length;
      const H = Math.max.apply(null, px), L = Math.min.apply(null, px);
      const pos = H === L ? 0.5 : (cur - L) / (H - L);
      let score = 50 + mom * 4;
      score += ma5 > ma10 ? 12 : -12;
      score += (pos - 0.5) * 20;
      const rsi = H === L ? 50 : 50 + (pos - 0.5) * 60;
      score = score * 0.7 + rsi * 0.3;
      return Math.max(0, Math.min(100, score));
    }
    function calcTgt(s) {
      const px = parseFloat(s.px);
      if (s.target && px) {
        const pct = (s.target - px) / px * 100;
        return (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%';
      }
      const span = 12 + s.alpha / 100 * 13;
      const e5 = (faceScore(s) - 50) / 50;
      const eK = (kTechScore(s) - 50) / 50;
      const pct = (0.7 * e5 + 0.3 * eK) * span;
      return (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%';
    }
    function rowHtml(code) {
      const s = CAND.find(x => x.c === code);
      if (!s) return '';
      const stars = s.alpha >= 92 ? 5 : s.alpha >= 86 ? 4 : 3;
      const starHtml = [1, 2, 3, 4, 5].map(i => '<span class="st' + (i <= stars ? '' : ' off') + '">★</span>').join('');
      const ringC = s.alpha >= 88 ? '#52C41A' : s.alpha >= 80 ? '#FF9800' : '#FF4D4F';
      const hitHtml = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(i => '<i class="' + (i <= s.hit ? 'on' : '') + '"></i>').join('');
      const bgCls = s.bg === '强势' ? 'strong' : (s.bg === '弱势' ? 'weak' : 'neutral');
      return '<tr><td>' + s.c + '</td><td>' + s.n + '</td><td>' + s.px + '</td>' +
        '<td><span class="' + (s.chg.startsWith('-') ? 'down' : 'up') + '">' + s.chg + '</span></td>' +
        '<td>' + s.tur + '</td><td>' + s.lb + '</td>' +
        '<td><span class="sector-chip">' + s.sec + '</span></td>' +
        '<td><span class="concept">' + s.con + '</span></td>' +
        '<td><div class="score-cell"><span class="score">' + s.alpha + '</span><span class="stars">' + starHtml + '</span></div></td>' +
        '<td><div class="ring" style="--p:' + s.entry + ';--ring-c:' + ringC + '"><span>' + s.entry + '</span></div></td>' +
        '<td><span class="hit-bar">' + hitHtml + '</span></td>' +
        '<td><span class="chip ' + bgCls + '">' + s.bg + '</span></td>' +
        '<td><span class="tgt" title="未来 20 个交易日(约 1 个月)· 5面加权 ' + faceScore(s).toFixed(0) + ' · K线技术 ' + kTechScore(s).toFixed(0) + ' · 基本面 ' + s.faces.fund + ' · 技术面 ' + s.faces.tech + ' · 资金面 ' + s.faces.flow + ' · 新闻面 ' + s.faces.news + ' · 情绪面 ' + s.faces.sent + '">' + calcTgt(s) + '</span></td>' +
        '<td><span class="' + (s.act.startsWith('-') ? 'down' : 'up') + '">' + s.act + '</span></td>' +
        '<td><span class="sel-day">' + s.sel + '</span></td>' +
        '<td><button class="as-remove" data-code="' + s.c + '" title="移除自选">✕</button></td></tr>';
    }
    function renderWatchlist() {
      const tbody = document.querySelector('#page-watchlist .pg-table table tbody');
      if (!tbody) return;
      tbody.innerHTML = getCodes().map(rowHtml).join('');
      updateCount();
    }
    function updateCount() {
      const tbody = document.querySelector('#page-watchlist .pg-table table tbody');
      const h2 = document.querySelector('#page-watchlist .pg-h2');
      const n = tbody ? tbody.querySelectorAll('tr').length : 0;
      if (h2) h2.textContent = '共 ' + n + ' 只关注标的 · 支持自定义分组';
      const badge = document.querySelector('.nav-item[data-page="watchlist"] .badge');
      if (badge) badge.textContent = n;
    }
    function handleAdd() {
      const input = document.getElementById('asInput');
      const kw = (input.value || '').trim();
      if (!kw) { setMsg('请输入股票代码或名称', false); return; }
      const exact = CAND.filter(s => s.c === kw);
      const fuzzy = CAND.filter(s => s.n.toLowerCase().includes(kw.toLowerCase()));
      const hit = exact.length ? exact[0] : (fuzzy.length ? fuzzy[0] : null);
      if (!hit) { setMsg('未找到「' + kw + '」,请尝试完整名称或 6 位代码', false); return; }
      const codes = getCodes();
      if (codes.indexOf(hit.c) !== -1) { setMsg(hit.n + ' ' + hit.c + ' 已在自选中', false); return; }
      codes.push(hit.c);
      saveCodes(codes);
      renderWatchlist();
      setMsg('✓ 已添加 <b>' + hit.n + ' ' + hit.c + '</b> 到自选', true);
      input.value = '';
    }
    function handleRemove(code) {
      saveCodes(getCodes().filter(c => c !== code));
      renderWatchlist();
    }
    const INTEL_NEWS = {
      '300308': [
        { t: '获 12 家券商上调目标价,一致预期均值 148.2 元(+59%),中报净利同比预增 110%', sent: 1, time: '10:24', src: '财联社', imp: 'CPO · 光模块' },
        { t: '英伟达 NVL72 出货上修,800G 光模块 Q3 订单环比 +25%,供需缺口扩大', sent: 1, time: '09:47', src: '证券时报', imp: '英伟达产业链' },
        { t: 'Q2 光模块出货 210 万只创单季新高,产能满载,毛利率环比 +2.1pct', sent: 1, time: '昨日', src: '公司公告', imp: '海外收入占比' },
        { t: '公司回应:800G 良率爬坡顺利,年内出货占比预计过半', sent: 1, time: '昨日', src: '机构调研', imp: '产品结构' },
        { t: '原始股东披露减持计划,拟减持不超 1.5% 股份,高位筹码松动', sent: -1, time: '09:51', src: '公司公告', imp: '股东减持' },

      ],
      '300502': [
        { t: '800G 新品通过北美云厂商认证,8 月批量出货,单季出货指引上修 30%', sent: 1, time: '09:58', src: '财联社', imp: '光模块 · 800G' },
        { t: '泰国工厂二期扩产落地,海外收入占比升至 55%,关税风险对冲', sent: 1, time: '昨日', src: '上证报', imp: '全球化布局' },
        { t: 'LPO 方案获海外客户认可,1.6T 送样进度超预期', sent: 1, time: '09:14', src: '证券时报', imp: '1.6T 光模块' },
        { t: '股权激励目标绑定 2026-2028 营收 CAGR 30%', sent: 1, time: '3 日前', src: '公司公告', imp: '公司治理' },
        { t: '板块短期涨幅过大,获利盘了结,资金高低切换迹象明显', sent: -1, time: '10:16', src: '财联社', imp: '资金面' },

      ],
      '300394': [
        { t: 'CPO 光器件核心供应商,配套北美大客户订单能见度至 Q4', sent: 1, time: '10:11', src: '财联社', imp: 'CPO 产业链' },
        { t: '无源光器件毛利率回升至 31%,陶瓷套管新品进入认证', sent: 1, time: '昨日', src: '证券时报', imp: '光器件 · 无源' },
        { t: '参股芯片公司 IPO 过会,投资收益增厚确定性增强', sent: 1, time: '昨日', src: '上证报', imp: '投资收益' },

      ],
      '002463': [
        { t: '英伟达新平台升级 PCB 用量,机构上修 Q3 出货预期至 +28%', sent: 1, time: '09:31', src: '证券时报', imp: 'PCB · AI 服务器' },
        { t: '高端 HDI 产能扩张 30%,AI 单机价值量提升逻辑兑现', sent: 1, time: '昨日', src: '财联社', imp: '算力硬件' },
        { t: '800G 交换机 PCB 认证通过,新客户导入落地', sent: 1, time: '昨日', src: '财联社', imp: '交换机 PCB' },
        { t: '铜价上行推升板材成本,机构提示 Q3 毛利率环比回落风险', sent: -1, time: '昨日', src: '证券时报', imp: '成本压力' },

      ],
      '002049': [
        { t: 'FPGA 国产替代加速,军用订单 Q3 确认收入,在手订单饱满', sent: 1, time: '08:55', src: '机构调研', imp: '军工芯片 · 特种IC' },
        { t: '特种集成电路需求回暖,存货去化接近尾声,毛利率企稳', sent: 1, time: '昨日', src: '上证报', imp: '国产替代' },
        { t: '控股股东增持计划启动,累计增持 2.3 亿元', sent: 1, time: '昨日', src: '公司公告', imp: '股东增持' },

      ],
      '601138': [
        { t: 'Q2 业绩符合预期,AI 服务器出货占比升至 41%,单季净利 +34%', sent: 1, time: '昨日 20:12', src: '公司公告', imp: 'AI 服务器 · 代工' },
        { t: '北美云厂商资本开支上调,液冷机柜订单排至明年 Q1', sent: 1, time: '昨日', src: '财联社', imp: '液冷散热' },
        { t: '拟回购 10-15 亿元用于股权激励,彰显经营信心', sent: 1, time: '昨日', src: '公司公告', imp: '回购' },
        { t: '代工模式毛利率承压,部分机构下调至中性评级', sent: -1, time: '昨日', src: '上证报', imp: '估值分歧' },

      ],
      '688256': [
        { t: '算力租赁订单落地,公告拟采购 4 万张训练卡,锁定 3 年需求', sent: 1, time: '09:47', src: '公司公告', imp: 'AI 芯片 · 算力' },
        { t: '国产训练芯片市占率提升,大模型客户扩产,推理需求爆发', sent: 1, time: '昨日', src: '财联社', imp: '国产算力' },
        { t: '推理芯片新品流片成功,单位算力成本下降 40%', sent: 1, time: '昨日', src: '财联社', imp: 'AI 芯片' },
        { t: '股价年内累计涨幅超 160%,解禁窗口临近,估值透支提示', sent: -1, time: '昨日', src: '财联社', imp: '解禁压力' },

      ],
      '688041': [
        { t: '国产 CPU 份额提升,信创集采中标大单,入围比例创历史新高', sent: 1, time: '10:02', src: '上证报', imp: 'CPU 国产化 · 信创' },
        { t: 'DCU 深算系列适配主流大模型框架,生态合作扩至 40+ 家', sent: 1, time: '昨日', src: '证券时报', imp: 'AI 生态' },
        { t: '三季报预告净利同比 +58%,订单确认提速', sent: 1, time: '昨日', src: '公司公告', imp: '业绩预告' },
        { t: '信创采购招标节奏慢于预期,部分订单确认延后至 Q4', sent: -1, time: '昨日', src: '上证报', imp: '招标节奏' },

      ],
      '603019': [
        { t: '算力基础设施订单饱满,液冷智算中心交付提速,在手订单 +42%', sent: 1, time: '09:44', src: '财联社', imp: '算力 · 信创' },
        { t: '信创整机出货回暖,毛利率环比改善 1.8pct,服务器业务放量', sent: 1, time: '昨日', src: '上证报', imp: '国产服务器' },
        { t: '中标某运营商智算中心 12.6 亿大单', sent: 1, time: '昨日', src: '交易所公告', imp: '智算中心' },
        { t: '存货周转天数上升,应收账款规模扩大,现金流承压', sent: -1, time: '昨日', src: '公司公告', imp: '现金流' },

      ],
      '688008': [
        { t: 'DDR5 渗透率提升,内存接口芯片量价齐升,涨价周期延续', sent: 1, time: '09:52', src: '财联社', imp: '存储芯片 · 内存接口' },
        { t: 'AI 服务器带动配套芯片需求,PCIe 6.0 新品送样龙头厂商', sent: 1, time: '昨日', src: '证券时报', imp: 'AI 服务器' },
        { t: 'PCIe 6.0 Retimer 芯片量产导入,打开第二成长曲线', sent: 1, time: '昨日', src: '财联社', imp: 'PCIe 6.0' },

      ],
      '000063': [
        { t: '国内 5G-A 建设提速,运营商集采份额领先,份额环比 +3pct', sent: 1, time: '09:36', src: '交易所公告', imp: '5G · 算力网络' },
        { t: '政企算力订单放量,服务器收入高增,第二曲线成型', sent: 1, time: '昨日', src: '财联社', imp: '政企算力' },
        { t: '拟 40 亿元投建国产算力服务器产业园', sent: 1, time: '昨日', src: '公司公告', imp: '算力基建' },
        { t: '运营商资本开支计划下修 5%,设备侧需求增速或放缓', sent: -1, time: '昨日', src: '财联社', imp: '资本开支' },

      ],
      '300750': [
        { t: '麒麟电池二代搭载新车上市,动力电池装机环比回升 15%', sent: 1, time: '10:05', src: '公司公告', imp: '动力电池 · 储能' },
        { t: '储能电池海外大单落地,欧洲工厂产能爬坡至 60%', sent: 1, time: '昨日', src: '证券时报', imp: '储能出海' },
        { t: '与欧洲车企签订 5 年供货长协,覆盖 2027-2032', sent: 1, time: '昨日', src: '财联社', imp: '欧洲市场' },
        { t: '神行超充电池装机突破 100 万辆', sent: 1, time: '3 日前', src: '公司公告', imp: '超充电池' },
        { t: '锂价低位震荡,电池行业价格战延续,单位盈利承压', sent: -1, time: '昨日', src: '证券时报', imp: '价格战' },

      ],
      '002594': [
        { t: '7 月新能源车销量创新高,出口占比升至三成,全年目标上调', sent: 1, time: '09:29', src: '公司公告', imp: '新能源车 · 出海' },
        { t: '高端车型放量,单车利润持续改善,智能化落地加速', sent: 1, time: '昨日', src: '财联社', imp: '智驾产业链' },
        { t: '欧洲反补贴关税落地,公司本土化建厂对冲影响', sent: -1, time: '昨日', src: '财联社', imp: '欧洲关税' },

      ],
      '600519': [
        { t: '批价回落至 2,240 元,经销商库存偏高,动销承压,渠道让利', sent: -1, time: '10:02', src: '证券时报', imp: '白酒 · 批价' },
        { t: '中秋旺季备货启动,飞天放量或加剧批价波动,库存周期拉长', sent: -1, time: '昨日', src: '财联社', imp: '消费板块' },
        { t: '直营渠道占比提升,茅台 1935 放量,产品结构升级', sent: 1, time: '昨日', src: '上证报', imp: '产品结构' },

      ],
      '601318': [
        { t: '保费收入同比负增长,寿险新单增速放缓,代理人队伍收缩', sent: -1, time: '09:12', src: '上证报', imp: '保险 · 寿险' },
        { t: '不动产敞口减值计提增加,市场担忧资产质量,股债双压', sent: -1, time: '昨日', src: '财联社', imp: '金融权重' },
        { t: '新金融监管口径下偿付能力充足率环比改善', sent: 1, time: '昨日', src: '上证报', imp: '监管指标' },

      ],
      '600900': [
        { t: '来水偏丰,汛期发电量超预期,电价稳中有升,盈利确定性增强', sent: 1, time: '昨日', src: '公司公告', imp: '电力 · 高股息' },
        { t: '六座电站 7 月发电量同比 +11%,蓄能充裕,全年指引上修', sent: 1, time: '3 日前', src: '上证报', imp: '水电板块' },
        { t: '拟上调年度分红比例至 85%,股息率升至 3.8%', sent: 1, time: '昨日', src: '公司公告', imp: '高股息' },

      ]
    };
    const RPT_BROKERS = ['中金公司', '中信建投', '国泰海通', '华泰证券', '招商证券', '申万宏源', '国信证券', '民生证券', '东方证券'];
    const RPT_POOL = [
      { r: '买入', v: '景气延续,订单能见度排至明年,上调盈利预测' },
      { r: '买入', v: '国产替代加速,份额提升逻辑持续兑现' },
      { r: '买入', v: '龙头地位强化,现金流优异,重申重点推荐' },
      { r: '增持', v: '行业需求回暖,估值处历史低位,具备修复空间' },
      { r: '增持', v: '新产能爬坡放量,量价齐升,关注 Q3 业绩弹性' },
      { r: '中性', v: '短期催化有限,等待行业需求与价格信号确认' }
    ];
    const RPT_CAT = ['中报业绩超预期、订单落地', '行业政策与新品发布', '下游资本开支上修、招标放量', '产品提价、毛利率拐点', '海外订单与产能投放'];
    function rpDateStr(code, i) {
      const day = 8 - Math.floor(rndInfo(code, 40 + i) * 13) - 1;
      if (day >= 1) return '08-' + String(day).padStart(2, '0');
      return '07-' + String(day + 31).padStart(2, '0');
    }
    function rndInfo(code, off) {
      const x = Math.sin((code * 7.31 + off * 13.77) % 10000) * 43758.5453;
      return x - Math.floor(x);
    }
    function buildIntel(s) {
      const F = s.faces || { fund: 50, tech: 50, flow: 50, news: 50, sent: 50 };
      const faceNames = { fund: '基本面', tech: '技术面', flow: '资金面', news: '新闻面', sent: '情绪面' };
      const faceIcons = { fund: '🏦', tech: '📈', flow: '💰', news: '📰', sent: '🔥' };
      const tagFor = v => v >= 70 ? 'strong' : (v >= 45 ? 'neutral' : 'weak');
      const vText = v => v >= 70 ? '强' : (v >= 45 ? '中' : '弱');
      const faces = Object.keys(FACE_W).map(k =>
        '<div class="intel-facet"><span class="intel-fname">' + faceIcons[k] + ' ' + faceNames[k] + ' <b>' + vText(F[k]) + '</b></span>' +
        '<div class="intel-fbar"><i style="width:' + F[k] + '%" class="' + (F[k] >= 70 ? 'good' : (F[k] >= 45 ? 'mid' : 'bad')) + '"></i></div>' +
        '<span class="intel-fval">' + F[k] + '</span></div>'
      ).join('');
      const fScore = faceScore(s);
      const kScore = kTechScore(s);
      const nws = INTEL_NEWS[s.c] || [];
      const r1 = rndInfo(s.c, 1), r2 = rndInfo(s.c, 2), r3 = rndInfo(s.c, 3);
      const reports = 6 + Math.round(r1 * 14);
      const buys = 3 + Math.round((reports * 0.55 * r2));
      const target = (parseFloat(s.px) * (1.08 + r3 * 0.18)).toFixed(1);
      const fundQ = (2 + rndInfo(s.c, 4) * 9).toFixed(1);
      const northDays = 1 + Math.round(rndInfo(s.c, 5) * 4);
      const mainFlow = (0.2 + rndInfo(s.c, 6) * 2.8).toFixed(1);
      const floatCap = (parseFloat(s.lb) * 0.35).toFixed(1);
      const instHtml =
        '<div class="intel-sec"><div class="intel-sec-t">🏛️ 机构动向</div>' +
        '<div class="intel-grid">' +
        '<div class="intel-cell"><span class="ic-k">基金 Q2 加仓</span><span class="ic-v up">+' + fundQ + '%</span></div>' +
        '<div class="intel-cell"><span class="ic-k">北向资金</span><span class="ic-v up">近 ' + northDays + ' 日净流入</span></div>' +
        '<div class="intel-cell"><span class="ic-k">主力净流入</span><span class="ic-v up">' + mainFlow + ' 亿</span></div>' +
        '<div class="intel-cell"><span class="ic-k">机构持有</span><span class="ic-v">' + floatCap + '% 流通</span></div>' +
        '</div></div>';
      const rpN = 4 + Math.round(rndInfo(s.c, 7) * 2);
      const usedB = [];
      const rpList = [];
      for (let i = 0; i < rpN; i++) {
        let bi = Math.floor(rndInfo(s.c, 10 + i) * RPT_BROKERS.length);
        let guard = 0;
        while (usedB.indexOf(bi) !== -1 && guard < RPT_BROKERS.length) { bi = (bi + 1) % RPT_BROKERS.length; guard++; }
        usedB.push(bi);
        const rp = RPT_POOL[Math.floor(rndInfo(s.c, 50 + i) * RPT_POOL.length)];
        const gain = rp.r === '中性' ? 2 + rndInfo(s.c, 61 + i) * 6 : 6 + rndInfo(s.c, 60 + i) * 20;
        const tp = (parseFloat(s.px) * (1 + gain / 100)).toFixed(1);
        const cat = RPT_CAT[Math.floor(rndInfo(s.c, 70 + i) * RPT_CAT.length)];
        const rateCls = rp.r === '买入' ? 'buy' : (rp.r === '增持' ? 'hold' : 'sell');
        const np = (2 + rndInfo(s.c, 80 + i) * 8).toFixed(1);
        const ng = (25 + rndInfo(s.c, 81 + i) * 40).toFixed(0);
        const pe = (20 + rndInfo(s.c, 82 + i) * 15).toFixed(0);
        rpList.push(
          '<div class="intel-rp">' +
          '<div class="rp-row1"><span class="rp-brk">' + RPT_BROKERS[bi] + '</span>' +
          '<span class="rp-date">' + rpDateStr(s.c, i) + '</span>' +
          '<span class="rp-rate ' + rateCls + '">' + rp.r + '</span>' +
          '<span class="rp-tp">目标 ' + tp + ' 元<span class="rp-gain">+' + gain.toFixed(1) + '%</span></span></div>' +
          '<div class="rp-row2"><span class="rp-logic">' + rp.v + '</span>' +
          '<span class="rp-cat">催化:' + cat + '</span></div>' +
          '<div class="rp-row3"><span class="rp-sum">摘要:预计 2026 年净利 ' + np + ' 亿(+' + ng + '%),对应 PE ' + pe + 'x,目标价隐含 ' + gain.toFixed(1) + '% 空间</span></div>' +
          '</div>');
      }
      const rpHtml =
        '<div class="intel-sec"><div class="intel-sec-t">📑 研报覆盖<span class="intel-sec-sub">近 3 月 ' + reports + ' 篇 · 买入 ' + buys + ' 家 · 目标 ' + target + ' 元</span></div>' +
        '<div class="intel-rp-list">' + rpList.join('') + '</div></div>';
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
      const bullPool = ['AI 算力高景气,订单能见度强', '国产替代加速,份额持续提升', '海外收入占比提升,盈利结构优化', '产品结构升级,毛利率拐点向上', '行业供需紧平衡,议价能力增强'];
      const bearPool = ['下游资本开支不及预期', '行业竞争加剧,价格承压', '估值处于历史高位', '政策与技术迭代风险', '原材料成本上升,毛利率承压'];
      const bull = bullPool[Math.floor(rndInfo(s.c, 90) * bullPool.length)];
      const bear = bearPool[Math.floor(rndInfo(s.c, 91) * bearPool.length)];
      const mv = (parseFloat(s.lb) * 100).toFixed(0);
      const ovHtml =
        '<div class="intel-sec"><div class="intel-sec-t">🏢 公司概览</div>' +
        '<div class="intel-ov-intro">' + s.n + ' 是国内' + s.sec + '领域核心公司,主营' + s.con.replace(' · ', '/') + '等业务,市值约 ' + mv + ' 亿元。公司所处行业景气度' + (fScore >= 60 ? '较高' : (fScore >= 45 ? '中性' : '偏弱')) + ',机构覆盖度处于行业中上水平。</div>' +
        '<div class="intel-ov-grid">' +
        '<div class="intel-ov-item"><span class="ov-k">🔑 核心看点</span><span class="ov-v">' + bull + '</span></div>' +
        '<div class="intel-ov-item"><span class="ov-k">⚠️ 风险提示</span><span class="ov-v down">' + bear + '</span></div>' +
        '</div></div>';
      return '<div class="intel-head"><div class="intel-hname">' + s.n + ' <span>' + s.c + '</span></div>' +
        '<div class="intel-hpx"><span class="' + (s.chg.startsWith('-') ? 'down' : 'up') + '">' + s.px + ' ' + s.chg + '</span><span class="intel-hmeta">' + s.sec + ' · ' + s.con + ' · 市值约 ' + mv + ' 亿</span></div></div>' +
        '<div class="intel-verdict ' + vCls + '"><span class="iv-chip">综合研判 · ' + vTxt + '</span><span class="iv-desc">' + vDesc + '</span>' +
        '<span class="iv-scores">5面 ' + fScore.toFixed(0) + ' · K线 ' + kScore.toFixed(0) + ' · 新闻 ' + newsScore.toFixed(0) + '</span></div>' +
        ovHtml +
        '<div class="intel-sec"><div class="intel-sec-t">🎯 5 面评分</div>' + faces + '</div>' +
        instHtml +
        '<div class="intel-cols">' +
        '<div class="intel-col-left">' + rpHtml + '</div>' +
        '<div class="intel-col-right">' + newsHtml + '</div>' +
        '</div>';
    }
    function handleIntel() {
      const input = document.getElementById('intelInput');
      const kw = (input.value || '').trim();
      const body = document.getElementById('intelBody');
      if (!kw) { body.innerHTML = '<div class="intel-empty">请输入股票代码或名称</div>'; return; }
      const exact = CAND.filter(s => s.c === kw);
      const fuzzy = CAND.filter(s => s.n.toLowerCase().includes(kw.toLowerCase()));
      const hit = exact.length ? exact[0] : (fuzzy.length ? fuzzy[0] : null);
      if (!hit) { body.innerHTML = '<div class="intel-empty">未找到「' + kw + '」,请尝试完整名称或 6 位代码</div>'; return; }
      body.innerHTML = buildIntel(hit);
      input.value = '';
    }
    renderWatchlist();

    document.addEventListener('click', e => {
      const tab = e.target.closest('.pg-flow-tab');
      if (tab) {
        const panel = tab.closest('.pg-panel');
        const fc = panel.querySelector('.pg-flow');
        panel.querySelectorAll('.pg-flow-tab').forEach(t => t.classList.toggle('active', t === tab));
        const pageId = fc.closest('.page').id.replace('page-', '');
        const page = PAGES[pageId];
        let block = page ? page.blocks.find(b => b.t === 'flowchart') : null;
        if (!block && pageId === 'market') block = INDEX_BLOCKS.find(b => b.t === 'flowchart');
        if (block) buildFlow(fc.querySelector('.pg-flow-body'), block, tab.dataset.mode);
        return;
      }
      const addBtn = e.target.closest('#asAddBtn');
      if (addBtn) { handleAdd(); return; }
      const rmBtn = e.target.closest('.as-remove');
      if (rmBtn) { handleRemove(rmBtn.dataset.code); return; }
      if (e.target.closest('#intelBtn')) { handleIntel(); return; }
    });
    document.addEventListener('keydown', e => {
      if (e.target.id === 'asInput' && e.key === 'Enter') handleAdd();
      if (e.target.id === 'intelInput' && e.key === 'Enter') handleIntel();
    });

    document.querySelectorAll('.nav-item[data-page]').forEach(n => {
      n.addEventListener('click', () => switchPage(n.dataset.page));
    });
    switchPage('market');
  });

})();

