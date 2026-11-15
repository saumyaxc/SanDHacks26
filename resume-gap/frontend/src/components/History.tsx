import { useState } from 'react'
import { groupByJob, type AnalysisSummary } from '../api'

const VISIBLE = 4

/** One row per job posting. Re-running a job with another resume adds a version, not a row. */
export function History({
  items,
  activeId,
  onSelect,
  onDeleteJob,
}: {
  items: AnalysisSummary[]
  activeId: string | null
  onSelect: (id: string) => void
  onDeleteJob: (ids: string[]) => void
}) {
  // Two-step delete: the first click asks, the second confirms. No browser dialog.
  const [confirming, setConfirming] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)
  if (items.length === 0) return null

  const jobs = groupByJob(items)
  // Keep the open analysis visible even when it's past the first few rows.
  const activeIndex = jobs.findIndex((versions) => versions.some((v) => v.id === activeId))
  const expanded = showAll || activeIndex >= VISIBLE
  const shown = expanded ? jobs : jobs.slice(0, VISIBLE)

  return (
    <nav className="history" aria-label="Past analyses">
      <h3>Past analyses</h3>
      <ul>
        {shown.map((versions) => {
          const newest = versions[0]
          const active = versions.some((v) => v.id === activeId)
          return (
            <li key={newest.job_key} className="history-row">
              <button
                type="button"
                className={`history-item ${active ? 'active' : ''}`}
                onClick={() => onSelect(newest.id)}
              >
                <span className="history-title">
                  {newest.role_title}
                  {newest.company && <span className="muted"> · {newest.company}</span>}
                </span>
                <span className="history-meta">
                  <strong>{newest.match_percent}% match</strong>
                  {versions.length > 1 && <span className="badge versions-badge">{versions.length} resumes</span>}
                  {' · '}
                  {new Date(newest.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                </span>
              </button>
              {confirming === newest.job_key ? (
                <span className="delete-confirm">
                  <button
                    type="button"
                    className="button-small danger"
                    onClick={() => {
                      setConfirming(null)
                      onDeleteJob(versions.map((v) => v.id))
                    }}
                  >
                    {versions.length > 1 ? `Delete ${versions.length}` : 'Delete'}
                  </button>
                  <button type="button" className="button-small" onClick={() => setConfirming(null)}>
                    Keep
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  className="icon-button"
                  aria-label={`Delete analyses for ${newest.role_title}`}
                  title="Delete"
                  onClick={() => setConfirming(newest.job_key)}
                >
                  ×
                </button>
              )}
            </li>
          )
        })}
      </ul>
      <ShowMore total={jobs.length} expanded={expanded} canCollapse={activeIndex < VISIBLE} onToggle={setShowAll} />
    </nav>
  )
}

export function ShowMore({
  total,
  expanded,
  canCollapse = true,
  onToggle,
}: {
  total: number
  expanded: boolean
  canCollapse?: boolean
  onToggle: (expanded: boolean) => void
}) {
  if (total <= VISIBLE || (expanded && !canCollapse)) return null
  return (
    <button type="button" className="show-more" onClick={() => onToggle(!expanded)}>
      {expanded ? 'Show less' : `Show ${total - VISIBLE} more`}
    </button>
  )
}
