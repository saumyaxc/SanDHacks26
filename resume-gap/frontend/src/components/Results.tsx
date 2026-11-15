import { useRef, useState } from 'react'
import {
  BUCKETS,
  type AnalysisResult,
  type Bucket,
  type EligibilityCheck,
  type EligibilityRequirement,
  type GapRecommendation,
  type MatchScore,
  type Requirement,
  type RequirementMatch,
  type ResourceType,
  type Rewrite,
  type Verdict,
} from '../api'
import { BUCKET_INFO } from '../buckets'

const RESOURCE_LABEL: Record<ResourceType, string> = {
  official_docs: 'Official docs',
  course: 'Course',
  tutorial: 'Tutorial',
  book: 'Book',
  video: 'Video',
  practice: 'Practice',
}

const VERDICT: Record<Verdict, { title: string; text: string }> = {
  strong: { title: 'Strong match', text: 'Worth applying now. Use the rewrites to make your fit obvious.' },
  tailor: { title: 'Worth applying, after tailoring', text: 'You have much of it; surface it better and close a gap or two.' },
  stretch: { title: 'A stretch', text: 'Several required skills are missing. Weigh the project time below before applying.' },
  not_eligible: {
    title: 'Likely not eligible',
    text: "You don't seem to meet a hard requirement below. Unless your resume is out of date, skip this one.",
  },
}

type Tab = 'match' | 'rewrites' | 'projects'

function scrollBehavior(): ScrollBehavior {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
}

export function Results({ result }: { result: AnalysisResult }) {
  const reqs = new Map(result.requirements.requirements.map((r) => [r.id, r]))
  // Traits (interest, mindset) aren't resume-provable: shown on their own, not in the buckets.
  const isTrait = (m: RequirementMatch) => reqs.get(m.requirement_id)?.category === 'trait'
  const matches = result.matches.matches.filter((m) => !isTrait(m))
  const traits = result.matches.matches.filter(isTrait)
  const rewrites = result.rewrites.rewrites
  const recommendations = result.recommendations.recommendations
  const { role_title, company } = result.requirements

  const [tab, setTab] = useState<Tab>('match')
  // Covered starts collapsed: it's the least actionable list.
  const [open, setOpen] = useState<Record<Bucket, boolean>>({
    covered: false,
    underemphasized: true,
    transferable: true,
    gap: true,
  })
  const sectionRefs = useRef<Partial<Record<Bucket, HTMLElement | null>>>({})

  function jumpTo(bucket: Bucket) {
    setTab('match')
    setOpen((o) => ({ ...o, [bucket]: true }))
    // Wait for the tab/section to render open before scrolling to it.
    requestAnimationFrame(() =>
      sectionRefs.current[bucket]?.scrollIntoView({ behavior: scrollBehavior(), block: 'start' }),
    )
  }

  return (
    <div className="results">
      <header className="results-header">
        <h2>
          {role_title}
          {company && <span className="company"> · {company}</span>}
        </h2>
      </header>

      <ScoreCard score={result.match_score} recommendations={recommendations} reqs={reqs} />
      <EligibilityPanel rules={result.requirements.eligibility ?? []} checks={result.matches.eligibility ?? []} />

      <div className="bucket-chips">
        {BUCKETS.map((b) => (
          <button key={b} type="button" className={`chip chip-${b}`} onClick={() => jumpTo(b)}>
            {matches.filter((m) => m.bucket === b).length} {BUCKET_INFO[b].label.toLowerCase()}
          </button>
        ))}
      </div>

      <div className="tabs" role="tablist" aria-label="Analysis sections">
        <TabButton id="match" current={tab} onSelect={setTab} label="Match" count={matches.length} />
        <TabButton id="rewrites" current={tab} onSelect={setTab} label="Rewrites" count={rewrites.length} />
        <TabButton id="projects" current={tab} onSelect={setTab} label="Projects" count={recommendations.length} />
      </div>

      <div role="tabpanel" aria-labelledby={`tab-${tab}`} className="tab-panel">
        {tab === 'match' &&
          BUCKETS.map((bucket) => (
            <BucketSection
              key={bucket}
              bucket={bucket}
              matches={matches}
              reqs={reqs}
              open={open[bucket]}
              onToggle={(isOpen) => setOpen((o) => ({ ...o, [bucket]: isOpen }))}
              sectionRef={(el) => {
                sectionRefs.current[bucket] = el
              }}
            />
          ))}
        {tab === 'match' && <TraitsSection traits={traits} reqs={reqs} />}
        {tab === 'rewrites' && <RewritesSection rewrites={rewrites} reqs={reqs} />}
        {tab === 'projects' && <ProjectsSection recommendations={recommendations} reqs={reqs} />}
      </div>
    </div>
  )
}

function TabButton({
  id,
  current,
  onSelect,
  label,
  count,
}: {
  id: Tab
  current: Tab
  onSelect: (t: Tab) => void
  label: string
  count: number
}) {
  const selected = id === current
  return (
    <button
      type="button"
      role="tab"
      id={`tab-${id}`}
      aria-selected={selected}
      className={`tab ${selected ? 'selected' : ''}`}
      onClick={() => onSelect(id)}
    >
      {label} <span className="tab-count">{count}</span>
    </button>
  )
}

function ScoreCard({
  score,
  recommendations,
  reqs,
}: {
  score: MatchScore
  recommendations: GapRecommendation[]
  reqs: Map<string, Requirement>
}) {
  // Time to close required gaps: the smallest project offered for each required gap.
  const requiredHours = recommendations
    .filter((r) => reqs.get(r.requirement_id)?.priority === 'required')
    .reduce((sum, r) => sum + Math.min(...r.projects.map((p) => p.estimated_hours)), 0)
  const verdict = VERDICT[score.verdict]
  const radius = 34
  const circumference = 2 * Math.PI * radius

  return (
    <section className={`score-card verdict-${score.verdict}`} aria-label="Overall match">
      <svg className="score-ring" viewBox="0 0 80 80" role="img" aria-label={`${score.percent}% match`}>
        <circle className="ring-track" cx="40" cy="40" r={radius} />
        <circle
          className="ring-fill"
          cx="40"
          cy="40"
          r={radius}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - score.percent / 100)}
        />
        <text x="40" y="40" className="ring-text">
          {score.percent}%
        </text>
      </svg>
      <div className="score-text">
        <h3>{verdict.title}</h3>
        <p className="muted">{verdict.text}</p>
        <p className="score-facts">
          <span>
            <strong>
              {score.required_met} of {score.required_total}
            </strong>{' '}
            required skills
          </span>
          {requiredHours > 0 && (
            <span>
              <strong>~{requiredHours}h</strong> of projects to close required gaps
            </span>
          )}
        </p>
        <details className="score-how">
          <summary>How is this calculated?</summary>
          <p>
            Each requirement earns credit: covered 100%, underemphasized 80%, transferable 40%, gap 0%. Required skills
            count double, and "any one of these" lists count once. It's a guide, not a verdict on you.
          </p>
        </details>
      </div>
    </section>
  )
}

const ELIGIBILITY_KIND: Record<EligibilityRequirement['kind'], string> = {
  degree_level: 'Degree level',
  enrollment: 'Enrollment',
  graduation_window: 'Graduation date',
  work_authorization: 'Work authorization',
  other: 'Requirement',
}

function EligibilityPanel({ rules, checks }: { rules: EligibilityRequirement[]; checks: EligibilityCheck[] }) {
  if (checks.length === 0) return null
  const rule = new Map(rules.map((r) => [r.id, r]))
  const notMet = checks.filter((c) => c.status === 'not_met')
  const unknown = checks.filter((c) => c.status === 'unknown')
  const met = checks.filter((c) => c.status === 'met')

  const row = (c: EligibilityCheck) => {
    const r = rule.get(c.eligibility_id)
    return (
      <li key={c.eligibility_id} className={`elig elig-${c.status}`}>
        <p className="elig-head">
          <span className="badge">{r ? ELIGIBILITY_KIND[r.kind] : 'Requirement'}</span> {r?.description}
        </p>
        {c.evidence_quote && <blockquote className="quote">{c.evidence_quote}</blockquote>}
        <p className="rationale">{c.rationale}</p>
        {r && (
          <details className="jd-quote">
            <summary>What the job says</summary>
            <p>“{r.jd_quote}”</p>
          </details>
        )}
      </li>
    )
  }

  return (
    <section className="eligibility" aria-label="Eligibility">
      {notMet.length > 0 && (
        <div className="elig-group elig-group-not_met" role="alert">
          <h3>You may not be eligible</h3>
          <p className="small">
            This job has hard requirements your resume doesn't meet. If that's right, your time is better spent on other
            roles.
          </p>
          <ul>{notMet.map(row)}</ul>
        </div>
      )}
      {unknown.length > 0 && (
        <div className="elig-group elig-group-unknown">
          <h3>Check these yourself</h3>
          <p className="small muted">Your resume doesn't say enough to tell.</p>
          <ul>{unknown.map(row)}</ul>
        </div>
      )}
      {met.length > 0 && (
        <details className="elig-group elig-group-met">
          <summary>
            ✓ You meet {met.length} eligibility requirement{met.length > 1 ? 's' : ''}
          </summary>
          <ul>{met.map(row)}</ul>
        </details>
      )}
    </section>
  )
}

function TraitsSection({ traits, reqs }: { traits: RequirementMatch[]; reqs: Map<string, Requirement> }) {
  if (traits.length === 0) return null
  return (
    <section className="section traits">
      <h3>Traits & interests</h3>
      <p className="muted small">
        Things like passion for the company or a growth mindset can't be proven by a resume line, so they don't count
        toward your match. Show them in your cover letter or interview instead.
      </p>
      <ul className="trait-list">
        {traits.map((m) => {
          const req = reqs.get(m.requirement_id)!
          return (
            <li key={m.requirement_id} className="trait">
              <div className="match-head">
                <span className="skill">{req.skill}</span>
                {m.bucket !== 'gap' && <span className="badge badge-shown">shown on your resume</span>}
              </div>
              {m.evidence_quote && <blockquote className="quote">{m.evidence_quote}</blockquote>}
              <p className="muted small">“{req.jd_quote}”</p>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function BucketSection({
  bucket,
  matches,
  reqs,
  open,
  onToggle,
  sectionRef,
}: {
  bucket: Bucket
  matches: RequirementMatch[]
  reqs: Map<string, Requirement>
  open: boolean
  onToggle: (open: boolean) => void
  sectionRef: (el: HTMLElement | null) => void
}) {
  const inBucket = matches
    .filter((m) => m.bucket === bucket)
    // Required first, then group-satisfied last; otherwise JD order (sort is stable).
    .sort((a, b) => rank(a, reqs) - rank(b, reqs))
  if (inBucket.length === 0) return null

  return (
    <section ref={sectionRef} className="section bucket-section">
      <details open={open} onToggle={(e) => onToggle(e.currentTarget.open)}>
        <summary>
          <span className={`bucket-title bucket-${bucket}`}>
            {BUCKET_INFO[bucket].label} <span className="count">{inBucket.length}</span>
          </span>
          <span className="muted small">{BUCKET_INFO[bucket].blurb}</span>
        </summary>
        <ul className="match-list">
          {inBucket.map((m) => (
            <MatchRow key={m.requirement_id} match={m} req={reqs.get(m.requirement_id)!} reqs={reqs} />
          ))}
        </ul>
      </details>
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
        {satisfiedBy ? (
          <span className="badge badge-optional">optional</span>
        ) : (
          <span className={`badge badge-${req.priority}`}>{req.priority}</span>
        )}
        {req.years_required != null && <span className="badge">{req.years_required}+ yrs</span>}
      </div>
      {satisfiedBy && (
        <p className="satisfied-note">
          The job accepts any one of these, and you have {satisfiedBy.skill}.
          {match.bucket === 'underemphasized' && ` Showing real ${req.skill} work would still strengthen your application.`}
        </p>
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
      <p className="muted section-intro">
        Same facts, worded so the skill is easier to spot. Nothing is added that your line doesn't already say.
      </p>
      {rewrites.length === 0 ? (
        <p className="empty">No rewrites suggested: your relevant lines already read clearly.</p>
      ) : (
        <ul className="card-list">
          {rewrites.map((rw) => (
            <li key={rw.evidence_id} className="card">
              <div className="rewrite-head">
                <p className="for-skills">For {rw.requirement_ids.map((id) => reqs.get(id)?.skill ?? id).join(', ')}</p>
                {rw.needs_confirmation && (
                  <span className="badge badge-confirm" title="Your line implies this but doesn't say it">
                    Only if true
                  </span>
                )}
              </div>
              {rw.needs_confirmation && (
                <p className="confirm-note small">
                  This names something your line implies but doesn't state. Use it only if you really did it.
                </p>
              )}
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
      <p className="muted section-intro">
        Pick one per gap. Each is small and finishable, and builds on what you already know.
      </p>
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
                </div>
                <ol className="project-list">
                  {rec.projects.map((p) => (
                    <li key={p.title} className="project">
                      <div className="project-head">
                        <h4>{p.title}</h4>
                        <span className="badge">~{p.estimated_hours}h</span>
                      </div>
                      <p>{p.description}</p>
                    </li>
                  ))}
                </ol>
                <ResourceLink rec={rec} />
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function ResourceLink({ rec }: { rec: GapRecommendation }) {
  const host = rec.resource_url_verified ? new URL(rec.resource_url).hostname.replace(/^www\./, '') : null
  return (
    <p className="resource">
      <span className="badge badge-resource">{RESOURCE_LABEL[rec.resource_type]}</span>
      <a href={rec.resource_url} target="_blank" rel="noopener noreferrer">
        {rec.resource_url_verified ? rec.resource_title : `Search: ${rec.resource_title}`}
      </a>
      {host ? (
        <span className="muted small" title="We checked this link loads">
          {host} ✓
        </span>
      ) : (
        <span className="muted small" title="We couldn't confirm an official link, so this opens a web search">
          (no checked link)
        </span>
      )}
    </p>
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
