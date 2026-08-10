import { Pct } from '../ui'

export default function Sectors({ sectors }: { sectors: { name: string; pct: number; weight: number }[] }) {
  return (
    <div className="space-y-2.5">
      {sectors.map((s) => (
        <div key={s.name}>
          <div className="flex items-center justify-between mb-1">
            <span style={{ color: 'var(--text)', fontSize: 12.5 }}>{s.name}</span>
            <Pct v={s.pct} />
          </div>
          <div style={{ height: 6, background: 'var(--bg-panel-2)', borderRadius: 4, overflow: 'hidden' }}>
            <div
              style={{
                width: `${Math.min(100, s.weight * 100)}%`,
                height: '100%',
                background: s.pct >= 0 ? 'var(--up)' : 'var(--down)',
                borderRadius: 4,
                opacity: 0.85,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}
