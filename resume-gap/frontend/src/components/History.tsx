import type { AnalysisSummary } from '../api'

export function History({
  items,
  activeId,
  onSelect,
}: {
  items: AnalysisSummary[]
  activeId: string | null
  onSelect: (id: string) => void
}) {
  if (items.length === 0) return null
  return (
    <nav className="history" aria-label="Past analyses">
      <h3>Past analyses</h3>
      <ul>
        {items.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              className={`history-item ${item.id === activeId ? 'active' : ''}`}
              onClick={() => onSelect(item.id)}
            >
              <span className="history-title">
                {item.role_title}
                {item.company && <span className="muted"> · {item.company}</span>}
              </span>
              <span className="history-meta">
                <strong>{item.match_percent}% match</strong>
                {' · '}
                {item.bucket_counts.transferable + item.bucket_counts.gap} to work on ·{' '}
                {new Date(item.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
