import React from 'react'

export function fmt(n: number | null | undefined, d = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })
}

export function pctClass(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return 'ink-dim'
  return v > 0 ? 'up' : 'down'
}

export function Pct({ v, d = 2, suffix = '%' }: { v: number | null | undefined; d?: number; suffix?: string }) {
  if (v === null || v === undefined || Number.isNaN(v)) return <span className="ink-dim">—</span>
  const sign = v > 0 ? '+' : ''
  return <span className={pctClass(v)}>{sign + v.toFixed(d) + suffix}</span>
}

export function Dot({ status }: { status: 'ok' | 'warn' | 'err' }) {
  const c = status === 'ok' ? 'var(--down)' : status === 'warn' ? 'var(--warn)' : 'var(--up)'
  return (
    <span
      style={{
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: c,
        boxShadow: `0 0 6px ${c}`,
      }}
    />
  )
}

export function Card({
  title,
  right,
  children,
  className = '',
}: {
  title?: string
  right?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={`panel p-3 flex flex-col ${className}`}>
      {(title || right) && (
        <header className="flex items-center justify-between mb-2.5">
          <h3 className="card-title">{title}</h3>
          {right}
        </header>
      )}
      {children}
    </section>
  )
}
