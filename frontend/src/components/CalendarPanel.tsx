export default function CalendarPanel({ events }: { events: { date: string; text: string }[] }) {
  return (
    <div className="space-y-2">
      {events.map((e, i) => (
        <div key={i} className="flex items-center gap-3">
          <div
            className="mono text-center px-2 py-1 rounded-md"
            style={{ background: 'var(--bg-panel-2)', color: 'var(--accent)', fontSize: 11, minWidth: 46 }}
          >
            {e.date}
          </div>
          <span style={{ color: 'var(--text)', fontSize: 12.5 }}>{e.text}</span>
        </div>
      ))}
    </div>
  )
}
