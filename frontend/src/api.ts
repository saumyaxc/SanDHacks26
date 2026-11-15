// Types mirror backend/app/domain/schemas.py — keep them in sync when the schemas change.

export type Bucket = 'covered' | 'underemphasized' | 'transferable' | 'gap'
export type Priority = 'required' | 'preferred'
export type SkillCategory = 'technology' | 'concept' | 'domain_knowledge' | 'soft_skill' | 'credential' | 'trait'
export type EligibilityKind = 'degree_level' | 'enrollment' | 'graduation_window' | 'work_authorization' | 'other'
export type EligibilityStatus = 'met' | 'not_met' | 'unknown'
export type ResumeSection = 'experience' | 'project' | 'education' | 'skills' | 'other'
export type ResourceType = 'official_docs' | 'course' | 'tutorial' | 'book' | 'video' | 'practice'

export const BUCKETS: Bucket[] = ['covered', 'underemphasized', 'transferable', 'gap']
export const MAX_INPUT_CHARS = 20_000

export interface Requirement {
  id: string
  skill: string
  canonical_skill: string
  category: SkillCategory
  priority: Priority
  years_required: number | null
  any_of_group: string | null
  jd_quote: string
}

export interface EligibilityRequirement {
  id: string
  kind: EligibilityKind
  description: string
  jd_quote: string
}

export interface EligibilityCheck {
  eligibility_id: string
  status: EligibilityStatus
  evidence_id: string | null
  evidence_quote: string | null
  rationale: string
}

export interface EvidenceItem {
  id: string
  section: ResumeSection
  line: string
  skills: { skill: string; canonical_skill: string }[]
}

export interface RequirementMatch {
  requirement_id: string
  bucket: Bucket
  evidence_id: string | null
  evidence_quote: string | null
  rationale: string
  satisfied_by: string | null // another member of its "any one of" list already meets the job's need
}

export interface Rewrite {
  evidence_id: string
  original_line: string
  suggested_line: string
  requirement_ids: string[]
  reason: string
  needs_confirmation: boolean // names something the line implies but doesn't state: "only if true"
}

export interface ProjectIdea {
  title: string
  description: string
  estimated_hours: number
}

export interface GapRecommendation {
  requirement_id: string
  projects: ProjectIdea[] // 1-3, smallest first
  resource_type: ResourceType
  resource_title: string
  resource_url: string // always works: a checked official link, or a web search
  resource_url_verified: boolean // false -> resource_url is a search link
}

export type Verdict = 'strong' | 'tailor' | 'stretch' | 'not_eligible'

export interface MatchScore {
  percent: number // 0-100, required skills weighted double
  required_met: number
  required_total: number
  skills_counted: number // requirements in the four buckets ("any one of these" lists count once)
  verdict: Verdict
}

export interface AnalysisResult {
  id: string
  session_id: string
  created_at: string
  jd_text: string // the saved job posting ("" for analyses saved before JDs were stored)
  resume_label: string // which resume it was run with ("resume.pdf", "pasted text")
  resume_hash: string // same resume text -> same value ("" for older analyses)
  job_key: string // equal for analyses of the same job posting
  requirements: {
    role_title: string
    company: string | null
    requirements: Requirement[]
    eligibility: EligibilityRequirement[]
  }
  evidence: { items: EvidenceItem[] }
  matches: { matches: RequirementMatch[]; eligibility: EligibilityCheck[] }
  rewrites: { rewrites: Rewrite[] }
  recommendations: { recommendations: GapRecommendation[] }
  match_score: MatchScore
}

export interface AnalysisSummary {
  id: string
  created_at: string
  role_title: string
  company: string | null
  bucket_counts: Record<Bucket, number>
  match_percent: number
  job_key: string
  resume_label: string
  resume_hash: string
}

/** A short, clean name for the resume an analysis used. */
export function resumeName(label: string): string {
  return label && label !== 'pasted text' ? label : 'Pasted resume'
}

/** How many different resumes a job's analyses used (re-runs of one resume count once). */
export function distinctResumes(versions: AnalysisSummary[]): number {
  return new Set(versions.map((v) => v.resume_hash || v.resume_label || v.id)).size
}

export interface ParsedResume {
  text: string // contact details already removed
  removed: string[] // e.g. ["name", "email", "link"]
}

export interface RankedGap {
  canonical_skill: string
  skill: string
  category: SkillCategory
  score: number
  job_count: number
  required_count: number
  occurrences: {
    analysis_id: string
    requirement_id: string
    role_title: string
    company: string | null
    bucket: Bucket
    priority: Priority
  }[] // newest first
  recommendation: GapRecommendation | null // newest projects suggested for this skill
}

export interface GapRanking {
  analysis_count: number
  gaps: RankedGap[]
  dismissed: string[] // canonical skills hidden from "Learn next"
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await send(path, init)
  return res.json() as Promise<T>
}

/** For endpoints that return 204 No Content. */
async function requestNoContent(path: string, init?: RequestInit): Promise<void> {
  await send(path, init)
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, init)
  } catch {
    throw new ApiError(0, "Can't reach the server. Is the backend running?")
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res))
  return res
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json()
    const detail = body?.detail
    if (typeof detail === 'string') return detail
    // FastAPI 422: a list of {loc, msg}; show the first readably.
    if (Array.isArray(detail) && detail[0]?.msg) {
      const field = detail[0].loc?.at(-1)
      return field ? `${field}: ${detail[0].msg}` : detail[0].msg
    }
  } catch {
    // not JSON; fall through
  }
  return `Request failed (${res.status})`
}

export function analyze(
  sessionId: string,
  jdText: string,
  resumeText: string,
  resumeLabel: string,
): Promise<AnalysisResult> {
  return request('/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      jd_text: jdText,
      resume_text: resumeText,
      resume_label: resumeLabel,
    }),
  })
}

/** Past analyses grouped by job posting, newest job first; each job's versions newest first. */
export function groupByJob(items: AnalysisSummary[]): AnalysisSummary[][] {
  const groups = new Map<string, AnalysisSummary[]>()
  for (const item of items) {
    const group = groups.get(item.job_key)
    if (group) group.push(item)
    else groups.set(item.job_key, [item])
  }
  return [...groups.values()]
}

export function parseResumePdf(file: File): Promise<ParsedResume> {
  const form = new FormData()
  form.append('file', file)
  return request('/resume/pdf', { method: 'POST', body: form })
}

export function listAnalyses(sessionId: string): Promise<AnalysisSummary[]> {
  return request(`/sessions/${encodeURIComponent(sessionId)}/analyses`)
}

export function getGapRanking(sessionId: string): Promise<GapRanking> {
  return request(`/sessions/${encodeURIComponent(sessionId)}/gaps`)
}

export function deleteAnalysis(sessionId: string, id: string): Promise<void> {
  return requestNoContent(`/sessions/${encodeURIComponent(sessionId)}/analyses/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
}

export function dismissGap(sessionId: string, canonicalSkill: string): Promise<void> {
  return requestNoContent(
    `/sessions/${encodeURIComponent(sessionId)}/dismissed-gaps/${encodeURIComponent(canonicalSkill)}`,
    { method: 'PUT' },
  )
}

export function restoreGap(sessionId: string, canonicalSkill: string): Promise<void> {
  return requestNoContent(
    `/sessions/${encodeURIComponent(sessionId)}/dismissed-gaps/${encodeURIComponent(canonicalSkill)}`,
    { method: 'DELETE' },
  )
}

export function getAnalysis(id: string): Promise<AnalysisResult> {
  return request(`/analyses/${encodeURIComponent(id)}`)
}

const SESSION_KEY = 'resume-gap.session-id'

/** A per-browser id that groups this user's analyses. Falls back to a per-tab id if storage is blocked. */
export function getSessionId(): string {
  try {
    const existing = localStorage.getItem(SESSION_KEY)
    if (existing) return existing
    const id = crypto.randomUUID()
    localStorage.setItem(SESSION_KEY, id)
    return id
  } catch {
    return (fallbackSessionId ??= crypto.randomUUID())
  }
}
let fallbackSessionId: string | undefined
