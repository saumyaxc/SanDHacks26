import { useState } from 'react'
import {
  BUCKETS,
  type AnalysisResult,
  type Bucket,
  type GapRecommendation,
  type Requirement,
  type RequirementMatch,
  type ResourceType,
  type Rewrite,
} from '../api'

const BUCKET_INFO: Record<Bucket, { label: string; blurb: string }> = {
  covered: { label: 'Covered', blurb: 'Your resume shows you doing this.' },
  underemphasized: { label: 'Underemphasized', blurb: 'You have it, but only list it or mention it in passing.' },
  transferable: { label: 'Transferable', blurb: "Not shown directly, but you've done something close." },
  gap: { label: 'Gap', blurb: 'Nothing on your resume supports this yet.' },
}

const RESOURCE_LABEL: Record<ResourceType, string> = {
  official_docs: 'Official docs',
  course: 'Course',
  tutorial: 'Tutorial',
  book: 'Book',
  video: 'Video',
  practice: 'Practice',
}

export function Results({ result }: { result: AnalysisResult }) {
  const reqs = new Map(result.requirements.requirements.map((r) => [r.id, r]))
  const matches = result.matches.matches
  const { role_title, company } = result.requirements

  return (
    <div className="results">
      <header className="results-header">
        <h2>
          {role_title}
          {company && <span className="company"> · {company}</span>}
        </h2>
        <div className="bucket-chips">
          {BUCKETS.map((b) => (
            <a key={b} href={`#bucket-${b}`} className={`chip chip-${b}`}>
              {matches.filter((m) => m.bucket === b).length} {BUCKET_INFO[b].label.toLowerCase()}
            </a>
          ))}
        </div>
      </header>

      {BUCKETS.map((bucket) => (
        <BucketSection key={bucket} bucket={bucket} matches={matches} reqs={reqs} />
      ))}

      <RewritesSection rewrites={result.rewrites.rewrites} reqs={reqs} />
      <ProjectsSection recommendations={result.recommendations.recommendations} reqs={reqs} />
    </div>
  )
}

function BucketSection({
  bucket,
  matches,
  reqs,
}: {
  bucket: Bucket
  matches: RequirementMatch[]
  reqs: Map<string, Requirement>
}) {
  const inBucket = matches
    .filter((m) => m.bucket === bucket)
    // Required first, then group-satisfied last; otherwise JD order (sort is stable).
    .sort((a, b) => rank(a, reqs) - rank(b, reqs))
  if (inBucket.length === 0) return null

  return (
    <section id={`bucket-${bucket}`} className="section">
      <h3 className={`bucket-title bucket-${bucket}`}>
        {BUCKET_INFO[bucket].label} <span className="count">{inBucket.length}</span>
      </h3>
      <p className="muted">{BUCKET_INFO[bucket].blurb}</p>
      <ul className="match-list">
        {inBucket.map((m) => (
          <MatchRow key={m.requirement_id} match={m} req={reqs.get(m.requirement_id)!} reqs={reqs} />
        ))}
      </ul>
    </section>
  )
}

function rank(m: RequirementMatch, reqs: Map<string, Requirement>): number {
  if (m.satisfied_by) return 2
  return reqs.get(m.requirement_id)?.priority === 'required' ? 0 : 1
}

function MatchRow({ match, req, reqs }: { match: RequirementMatch; req: Requirement; reqs: Map<string, Requirement> }) {
  const satisfiedBy = match.satisfied_by ? reqs.get(match.satisfied_by) : undefined
  return (
    <li className={`match ${satisfiedBy ? 'match-satisfied' : ''}`}>
      <div className="match-head">
        <span className="skill">{req.skill}</span>
        <span className={`badge badge-${req.priority}`}>{req.priority}</span>
        {req.years_required != null && <span className="badge">{req.years_required}+ yrs</span>}
      </div>
      {satisfiedBy && (
        <p className="satisfied-note">Not needed: the job accepts any one of these, and you have {satisfiedBy.skill}.</p>
      )}
      {match.evidence_quote && <blockquote className="quote">{match.evidence_quote}</blockquote>}
      <p className="rationale">{match.rationale}</p>
      <details className="jd-quote">
        <summary>What the job says</summary>
        <p>“{req.jd_quote}”</p>
      </details>
    </li>
  )
}

function RewritesSection({ rewrites, reqs }: { rewrites: Rewrite[]; reqs: Map<string, Requirement> }) {
  return (
    <section className="section">
      <h3>Suggested rewrites</h3>
      <p className="muted">Same facts, worded so the skill is easier to spot. Nothing is added that your line doesn't already say.</p>
      {rewrites.length === 0 ? (
        <p className="empty">No rewrites suggested: your relevant lines already read clearly.</p>
      ) : (
        <ul className="card-list">
          {rewrites.map((rw) => (
            <li key={rw.evidence_id} className="card">
              <p className="for-skills">For {rw.requirement_ids.map((id) => reqs.get(id)?.skill ?? id).join(', ')}</p>
              <p className="line-before">{rw.original_line}</p>
              <p className="line-after">{rw.suggested_line}</p>
              <div className="card-foot">
                <span className="muted">{rw.reason}</span>
                <CopyButton text={rw.suggested_line} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function ProjectsSection({
  recommendations,
  reqs,
}: {
  recommendations: GapRecommendation[]
  reqs: Map<string, Requirement>
}) {
  return (
    <section className="section">
      <h3>Weekend projects</h3>
      <p className="muted">One small, finishable project for each gap, built on what you already know.</p>
      {recommendations.length === 0 ? (
        <p className="empty">No gaps to fill. Nice.</p>
      ) : (
        <ul className="card-list">
          {recommendations.map((rec) => {
            const req = reqs.get(rec.requirement_id)
            return (
              <li key={rec.requirement_id} className="card">
                <div className="match-head">
                  <span className="skill">{req?.skill ?? rec.requirement_id}</span>
                  {req && <span className={`badge badge-${req.priority}`}>{req.priority}</span>}
                  <span className="badge">~{rec.estimated_hours}h</span>
                </div>
                <h4>{rec.project_title}</h4>
                <p>{rec.project_description}</p>
                <p className="resource">
                  <span className="badge badge-resource">{RESOURCE_LABEL[rec.resource_type]}</span> {rec.resource_suggestion}
                </p>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard can be blocked (permissions, insecure origin); the text is still selectable.
    }
  }
  return (
    <button type="button" className="button-small" onClick={copy}>
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}
