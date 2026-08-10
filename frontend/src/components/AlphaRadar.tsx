import type { AlphaRow } from '../types'

const actionColor: Record<AlphaRow['action'], string> = {
  BUY: 'var(--up)',
  HOLD: 'var(--text-dim)',
  WATCH: 'var(--accent)',
  SELL: 'var(--down)',
}

export default function AlphaRadar({ rows }: { rows: AlphaRow[] }) {
  return (
    <div className="overflow-auto" style={{ maxHeight: 320 }}>
      <table className="w-full text-[12.5px]">
        <thead className="sticky top-0" style={{ background: 'var(--bg-panel)' }}>
          <tr className="card-title">
            <th className="text-left font-semibold py-1.5 pl-1">#</th>
            <th className="text-left font-semibold py-1.5">股票</th>
            <th className="text-right font-semibold py-1.5">Alpha</th>
            <th className="text-right font-semibold py-1.5">入场</th>
            <th className="text-right font-semibold py-1.5">策略命中</th>
            <th className="text-left font-semibold py-1.5">环境</th>
            <th className="text-right font-semibold py-1.5 pr-1">动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.code} style={{ borderTop: '1px solid var(--border-soft)' }}>
              <td className="py-1.5 pl-1 mono" style={{ color: 'var(--text-dim)' }}>{r.rank}</td>
              <td className="py-1.5">
                <div className="mono" style={{ color: 'var(--text-hi)' }}>{r.code}</div>
                <div style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.name}</div>
              </td>
              <td className="text-right mono" style={{ color: 'var(--accent-2)', fontWeight: 600 }}>{r.alpha.toFixed(1)}</td>
              <td className="text-right mono" style={{ color: 'var(--text)' }}>{r.entry.toFixed(1)}</td>
              <td className="text-right mono" style={{ color: 'var(--text)' }}>{r.strategyHit} / 5</td>
              <td className="py-1.5" style={{ color: 'var(--text-dim)', fontSize: 12 }}>{r.context}</td>
              <td className="text-right pr-1 mono" style={{ color: actionColor[r.action], fontWeight: 600, fontSize: 12 }}>
                {r.action}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
