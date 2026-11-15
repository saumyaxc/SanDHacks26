import type { GapRanking } from '../api'

const MAX_SHOWN = 6

export function TopGaps({ ranking, onOpen }: { ranking: GapRanking | null; onOpen: (analysisId: string) => void }) {
  // One job's gaps are already on screen; ranking only adds something across several jobs.
  if (!ranking || ranking.analysis_count < 2 || ranking.gaps.length === 0) return null
  const top = ranking.gaps.slice(0, MAX_SHOWN)
  const maxScore = top[0].score

  return (
    <section className="top-gaps" aria-label="Top gaps across your jobs">
      <h3>Learn next</h3>
      <p className="muted small">Gaps across the {ranking.analysis_count} jobs you've analyzed, most useful first.</p>
      <ol>
        {top.map((g) => (
          <li key={g.canonical_skill}>
            <button type="button" className="gap-row" onClick={() => onOpen(g.occurrences[0].analysis_id)}>
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
          </li>
        ))}
      </ol>
    </section>
  )
}
