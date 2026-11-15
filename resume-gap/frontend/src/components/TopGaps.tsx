import { useState } from 'react'
import type { GapRanking } from '../api'
import { ShowMore } from './History'
import { ProjectPlan } from './Projects'

const VISIBLE = 4

export function TopGaps({
  ranking,
  onOpenAnalysis,
  onDismiss,
  onRestore,
}: {
  ranking: GapRanking | null
  onOpenAnalysis: (analysisId: string) => void
  onDismiss: (canonicalSkill: string) => void
  onRestore: (canonicalSkill: string) => void
}) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const [showHidden, setShowHidden] = useState(false)
  const [showAll, setShowAll] = useState(false)

  // One job's gaps are already on screen; ranking only adds something across several jobs.
  if (!ranking || ranking.analysis_count < 2) return null
  if (ranking.gaps.length === 0 && ranking.dismissed.length === 0) return null
  const top = showAll ? ranking.gaps : ranking.gaps.slice(0, VISIBLE)
  const maxScore = ranking.gaps[0]?.score ?? 1

  return (
    <section className="top-gaps" aria-label="Top gaps across your jobs">
      <h3>Learn next</h3>
      <p className="muted small">Gaps across the {ranking.analysis_count} jobs you've analyzed, most useful first.</p>
      <ol>
        {top.map((g) => {
          const open = expanded === g.canonical_skill
          const jobs = g.occurrences
          return (
            <li key={g.canonical_skill} className={`gap-item ${open ? 'open' : ''}`}>
              <button
                type="button"
                className="gap-row"
                aria-expanded={open}
                onClick={() => setExpanded(open ? null : g.canonical_skill)}
              >
                <span className="gap-row-head">
                  <span className="skill">{g.skill}</span>
                  <span className="muted small">
                    {g.job_count} of {ranking.analysis_count} jobs
                    {g.required_count > 0 && ` · ${g.required_count} required`}
                  </span>
                </span>
                <span className="gap-bar" aria-hidden="true">
                  <span style={{ width: `${(g.score / maxScore) * 100}%` }} />
                </span>
              </button>

              {open && (
                <div className="gap-detail">
                  {g.recommendation ? (
                    <ProjectPlan rec={g.recommendation} />
                  ) : (
                    <p className="muted small">No project suggestions saved for this skill yet.</p>
                  )}
                  <p className="small gap-jobs">
                    <span className="muted">Needed by: </span>
                    {jobs.map((o, i) => (
                      <span key={o.analysis_id}>
                        {i > 0 && ', '}
                        <button type="button" className="inline-link" onClick={() => onOpenAnalysis(o.analysis_id)}>
                          {o.role_title}
                          {o.company && ` · ${o.company}`}
                        </button>
                      </span>
                    ))}
                  </p>
                  <button
                    type="button"
                    className="button-small"
                    onClick={() => {
                      setExpanded(null)
                      onDismiss(g.canonical_skill)
                    }}
                  >
                    Hide from Learn next
                  </button>
                </div>
              )}
            </li>
          )
        })}
      </ol>
      <ShowMore total={ranking.gaps.length} expanded={showAll} onToggle={setShowAll} />

      {ranking.dismissed.length > 0 && (
        <div className="hidden-gaps small">
          <button type="button" className="inline-link muted" onClick={() => setShowHidden((v) => !v)}>
            {ranking.dismissed.length} hidden · {showHidden ? 'Hide list' : 'Show'}
          </button>
          {showHidden && (
            <ul>
              {ranking.dismissed.map((skill) => (
                <li key={skill}>
                  <span>{skill}</span>
                  <button type="button" className="inline-link" onClick={() => onRestore(skill)}>
                    Restore
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
