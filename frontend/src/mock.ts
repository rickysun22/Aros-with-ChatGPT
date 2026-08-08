import type { AlphaRow, Bar, IndexSnap, Stock } from './types'

// ---------- 确定性随机(按 code 播种,保证每次渲染一致) ----------
function rng(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 4294967296
  }
}
function hash(str: string): number {
  let h = 2166136261
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

export const mockStocks: Stock[] = [
  { code: '600000', name: '浦发银行' },
  { code: '600519', name: '贵州茅台' },
  { code: '000001', name: '平安银行' },
  { code: '300750', name: '宁德时代' },
  { code: '000858', name: '五粮液' },
  { code: '601318', name: '中国平安' },
  { code: '000333', name: '美的集团' },
  { code: '600036', name: '招商银行' },
]

interface WatchRow {
  code: string
  name: string
  price: number
  pct: number
  amount: number // 成交额(亿元)
  volume: number // 换手率 %
  marketCap: number // 总市值(亿元)
  pe: number
}
const base: Record<string, { price: number; pct: number }> = {
  '600000': { price: 9.82, pct: 1.24 },
  '600519': { price: 1685.0, pct: -0.86 },
  '000001': { price: 11.45, pct: 2.13 },
  '300750': { price: 192.3, pct: 3.45 },
  '000858': { price: 146.7, pct: -1.12 },
  '601318': { price: 49.2, pct: 0.62 },
  '000333': { price: 63.8, pct: 1.78 },
  '600036': { price: 35.6, pct: -0.34 },
}
export function mockWatchlist(): WatchRow[] {
  return mockStocks.map((s) => {
    const b = base[s.code]
    return {
      code: s.code,
      name: s.name,
      price: b.price,
      pct: b.pct,
      amount: +(Math.abs(b.pct) * 18 + 6).toFixed(1),
      volume: +(1 + Math.abs(b.pct) * 0.6).toFixed(2),
      marketCap: +(b.price * (s.code.startsWith('6') ? 290 : 120)).toFixed(0),
      pe: +(8 + Math.abs(hash(s.code) % 40)).toFixed(1),
    }
  })
}

export function mockAlpha(): AlphaRow[] {
  const arr = mockWatchlist()
    .map((w, i) => ({
      rank: i + 1,
      code: w.code,
      name: w.name,
      alpha: +(60 + (w.pct + 4) * 6).toFixed(1),
      entry: +(55 + w.pct * 5).toFixed(1),
      strategyHit: Math.max(0, Math.min(5, Math.round(2 + w.pct / 1.5))),
      context: w.pct > 0 ? 'Bull' : 'Neutral',
      action: (w.pct > 2 ? 'BUY' : w.pct < -1 ? 'SELL' : 'HOLD') as AlphaRow['action'],
    }))
    .sort((a, b) => b.alpha - a.alpha)
  return arr.map((r, i) => ({ ...r, rank: i + 1 }))
}

export function mockIndices(): IndexSnap[] {
  return [
    { code: '000001', name: '上证指数', close: 3284.56, pct: 0.72, date: '2026-06-30' },
    { code: '399001', name: '深证成指', close: 10512.34, pct: 1.13, date: '2026-06-30' },
    { code: '000300', name: '沪深300', close: 3921.08, pct: 0.91, date: '2026-06-30' },
  ]
}

// 合成日线(用于蜡烛图),确定性
export function mockBars(code: string): Bar[] {
  const r = rng(hash(code))
  const n = 180
  const end = new Date(2026, 5, 30)
  const out: Bar[] = []
  let prev = base[code]?.price ? base[code].price * 0.86 : 50
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(end)
    d.setDate(end.getDate() - i)
    if (d.getDay() === 0 || d.getDay() === 6) continue
    const drift = (r() - 0.48) * 0.03
    const close = +(prev * (1 + drift)).toFixed(2)
    const open = +(prev * (1 + (r() - 0.5) * 0.01)).toFixed(2)
    const high = +(Math.max(open, close) * (1 + r() * 0.012)).toFixed(2)
    const low = +(Math.min(open, close) * (1 - r() * 0.012)).toFixed(2)
    const vol = Math.round(5_000_000 + r() * 55_000_000)
    out.push({
      date: d.toISOString().slice(0, 10),
      open,
      high,
      low,
      close,
      volume: vol,
      amount: +(vol * close) / 100,
      change: +(close - prev).toFixed(2),
      pct: +(((close - prev) / prev) * 100).toFixed(2),
    })
    prev = close
  }
  return out
}

// mock 指标/因子最新值(供指标面板 + Alpha 因子列展示)
export function mockFactorLast(code: string) {
  const r = rng(hash(code) + 7)
  const pct = base[code]?.pct ?? 0
  return {
    ma_5: +(base[code]?.price * (1 + (r() - 0.5) * 0.02)).toFixed(2),
    ma_20: +(base[code]?.price * (1 + (r() - 0.5) * 0.03)).toFixed(2),
    ma_60: +(base[code]?.price * (1 + (r() - 0.5) * 0.04)).toFixed(2),
    rsi_14: +(45 + pct * 4 + (r() - 0.5) * 10).toFixed(1),
    macd: +((r() - 0.5) * 1.2).toFixed(3),
    macd_signal: +((r() - 0.5) * 1.0).toFixed(3),
    macd_hist: +((r() - 0.5) * 0.6).toFixed(3),
    kdj_k: +(40 + pct * 3 + r() * 10).toFixed(1),
    kdj_d: +(40 + pct * 2 + r() * 8).toFixed(1),
    kdj_j: +(40 + pct * 5 + r() * 14).toFixed(1),
    boll_mid_20: +(base[code]?.price * 0.99).toFixed(2),
    boll_upper_20: +(base[code]?.price * 1.06).toFixed(2),
    boll_lower_20: +(base[code]?.price * 0.93).toFixed(2),
    ma_dist_20: +(pct * 0.8).toFixed(2),
    macd_cross: pct > 0 ? 1 : -1,
    kdj_cross: r() > 0.5 ? 1 : -1,
    rsi_signal_14: pct > 1 ? 1 : pct < -1 ? -1 : 0,
    boll_pos_20: +(0.4 + r() * 0.4).toFixed(2),
    mom_5: +(pct * 0.5).toFixed(2),
    vol_ratio_5: +(0.6 + r() * 1.8).toFixed(2),
    ma_cross_5_20: pct > 0 ? 1 : -1,
  }
}

export function mockSectors() {
  return [
    { name: '半导体', pct: 2.84, weight: 0.82 },
    { name: '新能源', pct: 1.92, weight: 0.66 },
    { name: '白酒', pct: -1.34, weight: 0.58 },
    { name: '银行', pct: 0.62, weight: 0.71 },
    { name: '医药', pct: -0.45, weight: 0.49 },
    { name: '军工', pct: 1.05, weight: 0.4 },
  ]
}
export function mockAlerts() {
  return [
    { time: '14:32', text: '宁德时代 放量突破 20 日均线,MACD 金叉', tone: 'up' as const },
    { time: '13:58', text: '贵州茅台 跌破 BOLL 中轨,RSI 进入超买区', tone: 'down' as const },
    { time: '11:21', text: '半导体板块 资金净流入 +28.6 亿', tone: 'up' as const },
    { time: '10:05', text: '平安银行 量比放大至 2.3,换手率异动', tone: 'warn' as const },
    { time: '09:41', text: '上证指数 站上 3300 整数关口', tone: 'up' as const },
  ]
}
export function mockPortfolio() {
  return {
    total: 1284500,
    pnl: 3.82,
    positions: [
      { code: '600519', name: '贵州茅台', qty: 200, pnl: 5.1 },
      { code: '300750', name: '宁德时代', qty: 1500, pnl: 8.4 },
      { code: '601318', name: '中国平安', qty: 8000, pnl: -1.2 },
      { code: '000333', name: '美的集团', qty: 4000, pnl: 2.7 },
    ],
  }
}
export function mockSystem() {
  return [
    { name: '数据引擎', status: 'ok' as const, detail: 'AKShare / akshare-free 双通道' },
    { name: '指标引擎', status: 'ok' as const, detail: 'MA/RSI/MACD/KDJ/BOLL 就绪' },
    { name: '因子库', status: 'ok' as const, detail: '8 因子已加载' },
    { name: '数据新鲜度', status: 'warn' as const, detail: '最近同步 T-1' },
    { name: 'API 延迟', status: 'ok' as const, detail: '12ms' },
  ]
}
export function mockCalendar() {
  return [
    { date: '07-15', text: '国民经济运行数据发布' },
    { date: '07-18', text: 'MLF 续作窗口' },
    { date: '07-20', text: 'LPR 报价日' },
    { date: '07-25', text: '沪深300 调样生效' },
  ]
}
