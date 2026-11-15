import { useRef, useState } from 'react'
import {
  BUCKETS,
  type AnalysisResult,
  type AnalysisSummary,
  type Bucket,
  type EligibilityCheck,
  type EligibilityRequirement,
  type GapRecommendation,
  type MatchScore,
  type Requirement,
  type RequirementMatch,
  type Rewrite,
  type Verdict,
} from '../api'
import { BUCKET_INFO } from '../buckets'
import { ProjectPlan } from './Projects'

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

export function Results({
  result,
  versions,
  onSelectVersion,
  onTryAnotherResume,
}: {
  result: AnalysisResult
  versions: AnalysisSummary[] // every analysis of this same job, newest first
  onSelectVersion: (id: string) => void
  onTryAnotherResume: () => void
}) {
  const reqs = new Map(result.requirements.requirements.map((r) => [r.id, r]))
  // Soft skills and traits are judged in interviews, not resume lines (backend: INTERVIEW_CATEGORIES):
  // shown on their own, never as gaps.
  const isInterview = (m: RequirementMatch) => {
    const category = reqs.get(m.requirement_id)?.category
    return category === 'soft_skill' || category === 'trait'
  }
  // Degrees/certifications are qualifications, not skills: shown with eligibility, not in the buckets.
  const isCredential = (m: RequirementMatch) => reqs.get(m.requirement_id)?.category === 'credential'
  const credentials = result.matches.matches.filter(isCredential)
  const skillMatches = result.matches.matches.filter((m) => !isInterview(m) && !isCredential(m))
  // "Any one of these" lists: once one option is met, the others fold into its row
  // instead of appearing as separate cards with their own verdicts.
  const alternatives = new Map<string, RequirementMatch[]>()
  for (const m of skillMatches) {
    if (m.satisfied_by) alternatives.set(m.satisfied_by, [...(alternatives.get(m.satisfied_by) ?? []), m])
  }
  const matches = skillMatches.filter((m) => !m.satisfied_by)
  const interview = result.matches.matches.filter(isInterview)
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
        <div className="results-actions">
          {result.jd_text ? (
            <>
              <details className="jd-saved">
                <summary>Job description</summary>
                <pre>{result.jd_text}</pre>
              </details>
              <button type="button" className="button-small" onClick={onTryAnotherResume}>
                Try another resume
              </button>
            </>
          ) : (
            <p className="muted small">This older analysis didn't save its job description.</p>
          )}
        </div>
      </header>

      {versions.length > 1 && (
        <div className="version-tabs" role="tablist" aria-label="Resumes analyzed for this job">
          {versions.map((v) => {
            const selected = v.id === result.id
            return (
              <button
                key={v.id}
                type="button"
                role="tab"
                aria-selected={selected}
                className={`version-tab ${selected ? 'selected' : ''}`}
                onClick={() => !selected && onSelectVersion(v.id)}
              >
                <span className="version-name">{v.resume_label || 'Resume'}</span>
                <span className="muted small">
                  {new Date(v.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} ·{' '}
                  {v.match_percent}%
                </span>
              </button>
            )
          })}
        </div>
      )}

      <ScoreCard score={result.match_score} recommendations={recommendations} reqs={reqs} />
      <EligibilityPanel
        rules={result.requirements.eligibility ?? []}
        checks={result.matches.eligibility ?? []}
        credentials={credentials}
        reqs={reqs}
      />

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
              alternatives={alternatives}
              reqs={reqs}
              open={open[bucket]}
              onToggle={(isOpen) => setOpen((o) => ({ ...o, [bucket]: isOpen }))}
              sectionRef={(el) => {
                sectionRefs.current[bucket] = el
              }}
            />
          ))}
        {tab === 'match' && <InterviewSection items={interview} reqs={reqs} />}
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

type PanelItem = {
  key: string
  label: string // badge: "Degree level", "Credential", ...
  description: string
  status: 'met' | 'not_met' | 'unknown'
  quote: string | null
  rationale: string
  jdQuote: string | null
}

/** Hard requirements on the candidate: eligibility rules plus degrees/certifications. */
function EligibilityPanel({
  rules,
  checks,
  credentials,
  reqs,
}: {
  rules: EligibilityRequirement[]
  checks: EligibilityCheck[]
  credentials: RequirementMatch[]
  reqs: Map<string, Requirement>
}) {
  const rule = new Map(rules.map((r) => [r.id, r]))
  const items: PanelItem[] = [
    ...checks.map((c) => {
      const r = rule.get(c.eligibility_id)
      return {
        key: c.eligibility_id,
        label: r ? ELIGIBILITY_KIND[r.kind] : 'Requirement',
        description: r?.description ?? '',
        status: c.status,
        quote: c.evidence_quote,
        rationale: c.rationale,
        jdQuote: r?.jd_quote ?? null,
      }
    }),
    // A credential not found is "check yourself", never "not eligible": a related degree
    // often counts ("CS or a related field"), and only the candidate can judge that.
    ...credentials.map((m) => {
      const req = reqs.get(m.requirement_id)!
      return {
        key: m.requirement_id,
        label: 'Credential',
        description: req.priority === 'preferred' ? `${req.skill} (preferred)` : req.skill,
        status: m.bucket === 'gap' ? ('unknown' as const) : ('met' as const),
        quote: m.evidence_quote,
        rationale: m.bucket === 'gap' ? `Not found on your resume. ${m.rationale}` : m.rationale,
        jdQuote: req.jd_quote,
      }
    }),
  ]
  if (items.length === 0) return null
  const notMet = items.filter((i) => i.status === 'not_met')
  const unknown = items.filter((i) => i.status === 'unknown')
  const met = items.filter((i) => i.status === 'met')

  const row = (i: PanelItem) => (
    <li key={i.key} className={`elig elig-${i.status}`}>
      <p className="elig-head">
        <span className="badge">{i.label}</span> {i.description}
      </p>
      {i.quote && <blockquote className="quote">{i.quote}</blockquote>}
      <p className="rationale">{i.rationale}</p>
      {i.jdQuote && (
        <details className="jd-quote">
          <summary>What the job says</summary>
          <p>“{i.jdQuote}”</p>
        </details>
      )}
    </li>
  )

  return (
    <section className="eligibility" aria-label="Eligibility and credentials">
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
            ✓ You meet {met.length} eligibility &amp; education requirement{met.length > 1 ? 's' : ''}
          </summary>
          <ul>{met.map(row)}</ul>
        </details>
      )}
    </section>
  )
}

function InterviewSection({ items, reqs }: { items: RequirementMatch[]; reqs: Map<string, Requirement> }) {
  if (items.length === 0) return null
  return (
    <section className="section traits">
      <h3>For your cover letter & interview</h3>
      <p className="muted small">
        Soft skills, interests, and mindset (communication, prioritizing, passion for the company) are judged by people,
        not resume lines, so they don't count toward your match. Plan a story or a sentence for each.
      </p>
      <ul className="trait-list">
        {items.map((m) => {
          const req = reqs.get(m.requirement_id)!
          return (
            <li key={m.requirement_id} className="trait">
              <div className="match-head">
                <span className="skill">{req.skill}</span>
              </div>
              {m.evidence_quote ? (
                <>
                  <p className="muted small">An example you could use:</p>
                  <blockquote className="quote">{m.evidence_quote}</blockquote>
                </>
              ) : (
                <p className="muted small">No example on your resume yet, so have a story ready.</p>
              )}
              <p className="muted small">The job says: “{req.jd_quote}”</p>
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
  alternatives,
  reqs,
  open,
  onToggle,
  sectionRef,
}: {
  bucket: Bucket
  matches: RequirementMatch[]
  alternatives: Map<string, RequirementMatch[]>
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
            <MatchRow
              key={m.requirement_id}
              match={m}
              req={reqs.get(m.requirement_id)!}
              reqs={reqs}
              alternatives={alternatives.get(m.requirement_id) ?? []}
            />
          ))}
        </ul>
      </details>
    </section>
  )
}

function rank(m: RequirementMatch, reqs: Map<string, Requirement>): number {
  return reqs.get(m.requirement_id)?.priority === 'required' ? 0 : 1
}

const ALTERNATIVE_STATUS: Record<Bucket, string> = {
  covered: 'also on your resume',
  underemphasized: 'listed, not shown in use',
  transferable: 'related experience',
  gap: 'not on your resume',
}

function MatchRow({
  match,
  req,
  reqs,
  alternatives,
}: {
  match: RequirementMatch
  req: Requirement
  reqs: Map<string, Requirement>
  alternatives: RequirementMatch[] // other options from the same "any one of these" list
}) {
  return (
    <li className="match">
      <div className="match-head">
        <span className="skill">{req.skill}</span>
        <span className={`badge badge-${req.priority}`}>{req.priority}</span>
        {req.years_required != null && <span className="badge">{req.years_required}+ yrs</span>}
      </div>
      {match.evidence_quote && <blockquote className="quote">{match.evidence_quote}</blockquote>}
      <p className="rationale">{match.rationale}</p>
      {alternatives.length > 0 && (
        <div className="alternatives">
          <p className="small muted">
            The job accepts any one of these, and {req.skill} meets it. The others are optional:
          </p>
          <ul>
            {alternatives.map((alt) => {
              const altReq = reqs.get(alt.requirement_id)!
              return (
                <li key={alt.requirement_id} className="small">
                  <span className="alt-skill">{altReq.skill}</span>{' '}
                  <span className={`alt-status alt-${alt.bucket}`}>{ALTERNATIVE_STATUS[alt.bucket]}</span>
                </li>
              )
            })}
          </ul>
        </div>
      )}
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
                <ProjectPlan rec={rec} />
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
