import type { IndexSnap } from '../types'
import { Card, Pct } from '../ui'

export default function KpiRow({ indices }: { indices: IndexSnap[] }) {
  const sh = indices.find((i) => i.code === '000001')
  const sz = indices.find((i) => i.code === '399001')
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <Kpi label="上证指数" value={sh?.close} pct={sh?.pct} />
      <Kpi label="深证成指" value={sz?.close} pct={sz?.pct} />
      <Kpi label="两市成交额" value={12845} suffix="亿" />
      <Kpi label="活跃策略" value={12} suffix="" />
    </div>
  )
}

function Kpi({ label, value, pct, suffix = '' }: { label: string; value?: number; pct?: number; suffix?: string }) {
  return (
    <Card className="!p-3.5">
      <div className="card-title mb-1.5">{label}</div>
      <div className="mono" style={{ color: 'var(--text-hi)', fontSize: 22, fontWeight: 600 }}>
        {value !== undefined ? value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}
        <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>{suffix}</span>
      </div>
      {pct !== undefined && (
        <div className="mt-0.5 text-[12px]">
          <Pct v={pct} />
        </div>
      )}
    </Card>
  )
}
