import type { ReactNode } from 'react'

type V = number | null | undefined

function Bar({ value, max = 100, color = 'var(--accent)' }: { value: V; max?: number; color?: string }) {
  const pct = value == null || isNaN(value) ? 0 : Math.max(0, Math.min(100, (value / max) * 100))
  return (
    <div style={{ height: 4, background: 'var(--bg-panel-2)', borderRadius: 3, overflow: 'hidden', marginTop: 4 }}>
      <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3 }} />
    </div>
  )
}

function Cross({ v }: { v: V }) {
  if (v == null || isNaN(v as number)) return <span style={{ color: 'var(--text-dim)' }}>—</span>
  const map: Record<number, { t: string; c: string }> = {
    1: { t: '多头', c: 'var(--up)' },
    [-1]: { t: '空头', c: 'var(--down)' },
    0: { t: '中性', c: 'var(--text-dim)' },
  }
  const m = map[v as number] ?? map[0]
  return <span className="mono" style={{ color: m.c, fontWeight: 600 }}>{m.t}</span>
}

function Cell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="panel-2 px-2.5 py-2">
      <div className="card-title" style={{ marginBottom: 2 }}>{label}</div>
      {children}
    </div>
  )
}

export default function IndicatorPanel({ last, price, pct }: { last: Record<string, V>; price?: V; pct?: V }) {
  const num = (k: string) => last[k]
  const f2 = (v: V) => (v == null || isNaN(v as number) ? '—' : (v as number).toFixed(2))
  const f1 = (v: V) => (v == null || isNaN(v as number) ? '—' : (v as number).toFixed(1))

  return (
    <div className="space-y-3">
      {price !== undefined && (
        <div className="flex items-end justify-between">
          <div>
            <div className="card-title mb-1">最新价</div>
            <div className="mono" style={{ color: 'var(--text-hi)', fontSize: 22, fontWeight: 600 }}>
              {price == null ? '—' : (price as number).toFixed(2)}
            </div>
          </div>
          <div className="text-right">
            <div className="card-title mb-1">涨跌幅</div>
            <div className={`mono text-[16px] ${pct && (pct as number) >= 0 ? 'up' : 'down'}`}>
              {(pct ?? 0) >= 0 ? '+' : ''}
              {pct == null ? '—' : (pct as number).toFixed(2)}%
            </div>
          </div>
        </div>
      )}

      <div>
        <div className="card-title mb-2">技术指标 (IndicatorEngine)</div>
        <div className="grid grid-cols-3 gap-2">
          <Cell label="MA5">{f2(num('ma_5'))}</Cell>
          <Cell label="MA20">{f2(num('ma_20'))}</Cell>
          <Cell label="MA60">{f2(num('ma_60'))}</Cell>
          <Cell label="RSI(14)">{f1(num('rsi_14'))}<Bar value={num('rsi_14')} /></Cell>
          <Cell label="KDJ-K">{f1(num('kdj_k'))}</Cell>
          <Cell label="KDJ-D">{f1(num('kdj_d'))}</Cell>
          <Cell label="MACD">{f3(num('macd'))}</Cell>
          <Cell label="MACD Signal">{f3(num('macd_signal'))}</Cell>
          <Cell label="MACD Hist">{f3(num('macd_hist'))}</Cell>
          <Cell label="BOLL 上">{f2(num('boll_upper_20'))}</Cell>
          <Cell label="BOLL 中">{f2(num('boll_mid_20'))}</Cell>
          <Cell label="BOLL 下">{f2(num('boll_lower_20'))}</Cell>
        </div>
      </div>

      <div>
        <div className="card-title mb-2">因子信号 (FactorEngine)</div>
        <div className="grid grid-cols-2 gap-2">
          <Cell label="MA 距离 %">{f2(num('ma_dist_20'))}</Cell>
          <Cell label="价格/布林位置">{f2(num('boll_pos_20'))}<Bar value={(num('boll_pos_20') ?? 0) * 100} /></Cell>
          <Cell label="MACD 交叉"><Cross v={num('macd_cross')} /></Cell>
          <Cell label="KDJ 交叉"><Cross v={num('kdj_cross')} /></Cell>
          <Cell label="MA 交叉"><Cross v={num('ma_cross_5_20')} /></Cell>
          <Cell label="RSI 信号"><Cross v={num('rsi_signal_14')} /></Cell>
          <Cell label="动量(5) %">{f2(num('mom_5'))}</Cell>
          <Cell label="量比(5)">{f2(num('vol_ratio_5'))}</Cell>
        </div>
      </div>
    </div>
  )
}

function f3(v: V) {
  return v == null || isNaN(v as number) ? '—' : (v as number).toFixed(3)
}
