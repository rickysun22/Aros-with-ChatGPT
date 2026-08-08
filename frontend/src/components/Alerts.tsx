export default function Alerts({
  alerts,
}: {
  alerts: { time: string; text: string; tone: 'up' | 'down' | 'warn' }[]
}) {
  const color: Record<string, string> = {
    up: 'var(--up)',
    down: 'var(--down)',
    warn: 'var(--warn)',
  }
  return (
    <div className="space-y-2.5">
      {alerts.map((a, i) => (
        <div key={i} className="flex gap-2.5">
          <div style={{ width: 3, borderRadius: 3, background: color[a.tone], flexShrink: 0 }} />
          <div className="flex-1">
            <div style={{ color: 'var(--text-hi)', fontSize: 12.5 }}>{a.text}</div>
            <div className="mono" style={{ color: 'var(--text-dim)', fontSize: 11 }}>{a.time}</div>
          </div>
        </div>
      ))}
    </div>
  )
}
