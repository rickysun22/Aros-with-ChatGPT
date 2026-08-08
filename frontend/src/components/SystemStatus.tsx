import { Dot } from '../ui'

export default function SystemStatus({
  items,
}: {
  items: { name: string; status: 'ok' | 'warn' | 'err'; detail: string }[]
}) {
  return (
    <div className="space-y-2">
      {items.map((it) => (
        <div key={it.name} className="flex items-center gap-2.5">
          <Dot status={it.status} />
          <div className="flex-1 flex items-center justify-between">
            <span style={{ color: 'var(--text)', fontSize: 12.5 }}>{it.name}</span>
            <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{it.detail}</span>
          </div>
        </div>
      ))}
    </div>
  )
}
