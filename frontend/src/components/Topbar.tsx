import type { IndexSnap } from '../types'
import { Pct } from '../ui'

function greet(): string {
  const h = new Date().getHours()
  if (h < 6) return '凌晨好'
  if (h < 12) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
}

export default function Topbar({
  indices,
  mode,
  theme,
  onToggleTheme,
}: {
  indices: IndexSnap[]
  mode: 'live' | 'mock'
  theme: 'dark' | 'light'
  onToggleTheme: () => void
}) {
  return (
    <header
      className="flex items-center gap-4 px-5 py-3"
      style={{ borderBottom: '1px solid var(--border)', background: 'rgba(17,21,31,0.72)', backdropFilter: 'blur(12px)' }}
    >
      <div className="text-[15px]" style={{ color: 'var(--text-hi)', fontWeight: 600 }}>
        {greet()}, <span style={{ color: 'var(--accent)' }}>Ricky</span>
      </div>

      <div className="flex items-center gap-2 ml-1">
        {indices.map((ix) => (
          <div
            key={ix.code}
            className="panel-2 px-2.5 py-1 flex items-center gap-2"
            title={ix.name}
          >
            <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>{ix.name}</span>
            <span className="mono" style={{ color: 'var(--text-hi)', fontSize: 13 }}>
              {ix.close.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
            <Pct v={ix.pct} />
          </div>
        ))}
      </div>

      <div className="flex-1" />

      <div
        className="flex items-center px-3 py-1.5 rounded-md"
        style={{ background: 'var(--bg-panel-2)', border: '1px solid var(--border-soft)', width: 220 }}
      >
        <span style={{ color: 'var(--text-dim)' }}>🔍</span>
        <input
          placeholder="搜索股票 / 因子 / 策略…"
          className="bg-transparent outline-none text-[13px] px-2 w-full"
          style={{ color: 'var(--text-hi)' }}
        />
      </div>

      <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md" style={{ background: 'var(--bg-panel-2)' }}>
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: mode === 'live' ? 'var(--down)' : 'var(--warn)',
            boxShadow: `0 0 6px ${mode === 'live' ? 'var(--down)' : 'var(--warn)'}`,
          }}
        />
        <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
          {mode === 'live' ? 'AROS API' : '演示数据'}
        </span>
      </div>

      <button
        onClick={onToggleTheme}
        className="panel-2 px-2.5 py-1.5 rounded-md text-[13px]"
        style={{ color: 'var(--text)' }}
        title="切换主题"
      >
        {theme === 'dark' ? '🌙' : '☀️'}
      </button>
    </header>
  )
}
