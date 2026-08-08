import { Pct } from '../ui'

interface Portfolio {
  total: number
  pnl: number
  positions: { code: string; name: string; qty: number; pnl: number }[]
}

export default function PaperPortfolio({ p }: { p: Portfolio }) {
  return (
    <div className="space-y-3">
      <div className="flex items-end justify-between">
        <div>
          <div className="card-title mb-1">组合净值</div>
          <div className="mono" style={{ color: 'var(--text-hi)', fontSize: 20, fontWeight: 600 }}>
            ¥{p.total.toLocaleString('zh-CN')}
          </div>
        </div>
        <div className="text-right">
          <div className="card-title mb-1">当日</div>
          <div className="mono text-[16px]">
            <Pct v={p.pnl} />
          </div>
        </div>
      </div>
      <div className="space-y-1.5">
        {p.positions.map((pos) => (
          <div key={pos.code} className="flex items-center justify-between text-[12.5px]">
            <div>
              <span className="mono" style={{ color: 'var(--text-hi)' }}>{pos.code}</span>{' '}
              <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{pos.name}</span>
            </div>
            <Pct v={pos.pnl} />
          </div>
        ))}
      </div>
    </div>
  )
}
