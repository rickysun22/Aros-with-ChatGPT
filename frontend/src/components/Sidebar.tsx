interface NavItem {
  label: string
  badge?: number
}
const GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: '分析',
    items: [
      { label: 'Dashboard' },
      { label: 'Market Overview' },
      { label: 'Alpha Radar', badge: 8 },
      { label: 'Stock Intelligence' },
      { label: 'Strategy Lab' },
    ],
  },
  {
    title: '组合',
    items: [{ label: 'Portfolio' }, { label: 'Paper Trading' }, { label: 'Risk Monitor' }],
  },
  {
    title: '其它',
    items: [{ label: 'AI Research' }, { label: 'Calendar' }, { label: 'Reports' }, { label: 'Settings' }],
  },
]

export default function Sidebar({ active, onSelect }: { active: string; onSelect: (s: string) => void }) {
  return (
    <aside
      className="flex flex-col"
      style={{ width: 236, background: 'var(--bg-panel)', borderRight: '1px solid var(--border)' }}
    >
      <div className="flex items-center gap-2.5 px-4 py-4" style={{ borderBottom: '1px solid var(--border-soft)' }}>
        <div
          style={{
            width: 30,
            height: 30,
            borderRadius: 8,
            background: 'linear-gradient(135deg,var(--accent),var(--accent-2))',
            display: 'grid',
            placeItems: 'center',
            color: '#fff',
            fontWeight: 700,
            fontSize: 15,
          }}
        >
          A
        </div>
        <div className="leading-tight">
          <div style={{ color: 'var(--text-hi)', fontWeight: 700, fontSize: 14 }}>AROS</div>
          <div style={{ color: 'var(--text-dim)', fontSize: 10, letterSpacing: '0.08em' }}>RESEARCH OS</div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-2.5 py-3 space-y-4">
        {GROUPS.map((g) => (
          <div key={g.title}>
            <div className="card-title px-2 mb-1.5">{g.title}</div>
            {g.items.map((it) => {
              const isActive = it.label === active
              return (
                <button
                  key={it.label}
                  onClick={() => onSelect(it.label)}
                  className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-md text-left transition-colors"
                  style={{
                    color: isActive ? 'var(--text-hi)' : 'var(--text)',
                    background: isActive ? 'var(--bg-hover)' : 'transparent',
                    fontSize: 13,
                    fontWeight: isActive ? 600 : 400,
                  }}
                >
                  <span>{it.label}</span>
                  {it.badge !== undefined && (
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 700,
                        background: 'var(--accent-2)',
                        color: '#fff',
                        borderRadius: 6,
                        padding: '1px 6px',
                      }}
                    >
                      {it.badge}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        ))}
      </nav>

      <div className="flex items-center gap-2.5 px-4 py-3" style={{ borderTop: '1px solid var(--border-soft)' }}>
        <div
          style={{
            width: 30,
            height: 30,
            borderRadius: '50%',
            background: 'var(--bg-hover)',
            display: 'grid',
            placeItems: 'center',
            color: 'var(--text-hi)',
            fontWeight: 700,
            fontSize: 13,
          }}
        >
          R
        </div>
        <div className="leading-tight">
          <div style={{ color: 'var(--text-hi)', fontSize: 13, fontWeight: 600 }}>Ricky</div>
          <div style={{ color: 'var(--text-dim)', fontSize: 11 }}>Pro · 已连接</div>
        </div>
      </div>
    </aside>
  )
}
