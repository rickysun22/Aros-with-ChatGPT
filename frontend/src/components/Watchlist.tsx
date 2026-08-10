import { Pct } from '../ui'

export interface WatchRow {
  code: string
  name: string
  price: number
  pct: number
  amount: number
  volume: number
  marketCap: number
  pe: number
}

export default function Watchlist({
  rows,
  selected,
  onSelect,
}: {
  rows: WatchRow[]
  selected: string
  onSelect: (code: string) => void
}) {
  return (
    <div className="overflow-auto" style={{ maxHeight: 320 }}>
      <table className="w-full text-[12.5px]">
        <thead className="sticky top-0" style={{ background: 'var(--bg-panel)' }}>
          <tr className="card-title">
            <th className="text-left font-semibold py-1.5 pl-1">代码 / 名称</th>
            <th className="text-right font-semibold py-1.5">最新价</th>
            <th className="text-right font-semibold py-1.5">涨跌幅</th>
            <th className="text-right font-semibold py-1.5">成交额</th>
            <th className="text-right font-semibold py-1.5">换手</th>
            <th className="text-right font-semibold py-1.5">总市值</th>
            <th className="text-right font-semibold py-1.5 pr-1">PE</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const sel = r.code === selected
            return (
              <tr
                key={r.code}
                onClick={() => onSelect(r.code)}
                className="cursor-pointer transition-colors"
                style={{ background: sel ? 'var(--bg-hover)' : 'transparent' }}
                onMouseEnter={(e) => {
                  if (!sel) e.currentTarget.style.background = 'var(--bg-panel-2)'
                }}
                onMouseLeave={(e) => {
                  if (!sel) e.currentTarget.style.background = 'transparent'
                }}
              >
                <td className="py-1.5 pl-1">
                  <div className="mono" style={{ color: 'var(--text-hi)' }}>{r.code}</div>
                  <div style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.name}</div>
                </td>
                <td className="text-right mono" style={{ color: 'var(--text-hi)' }}>{r.price.toFixed(2)}</td>
                <td className="text-right mono"><Pct v={r.pct} /></td>
                <td className="text-right mono" style={{ color: 'var(--text)' }}>{r.amount.toFixed(1)}亿</td>
                <td className="text-right mono" style={{ color: 'var(--text)' }}>{r.volume.toFixed(2)}%</td>
                <td className="text-right mono" style={{ color: 'var(--text)' }}>{r.marketCap}亿</td>
                <td className="text-right mono pr-1" style={{ color: 'var(--text)' }}>{r.pe.toFixed(1)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
