// Types mirror backend/app/domain/schemas.py — keep them in sync when the schemas change.

export type Bucket = 'covered' | 'underemphasized' | 'transferable' | 'gap'
export type Priority = 'required' | 'preferred'
export type SkillCategory = 'technology' | 'concept' | 'domain_knowledge' | 'soft_skill' | 'credential'
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
  satisfied_by: string | null
}

export interface Rewrite {
  evidence_id: string
  original_line: string
  suggested_line: string
  requirement_ids: string[]
  reason: string
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

export interface AnalysisResult {
  id: string
  session_id: string
  created_at: string
  requirements: { role_title: string; company: string | null; requirements: Requirement[] }
  evidence: { items: EvidenceItem[] }
  matches: { matches: RequirementMatch[] }
  rewrites: { rewrites: Rewrite[] }
  recommendations: { recommendations: GapRecommendation[] }
}

export interface AnalysisSummary {
  id: string
  created_at: string
  role_title: string
  company: string | null
  bucket_counts: Record<Bucket, number>
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
    role_title: string
    company: string | null
    bucket: Bucket
    priority: Priority
  }[] // newest first
}

export interface GapRanking {
  analysis_count: number
  gaps: RankedGap[]
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, init)
  } catch {
    throw new ApiError(0, "Can't reach the server. Is the backend running?")
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res))
  return res.json() as Promise<T>
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

export function analyze(sessionId: string, jdText: string, resumeText: string): Promise<AnalysisResult> {
  return request('/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, jd_text: jdText, resume_text: resumeText }),
  })
}

export function listAnalyses(sessionId: string): Promise<AnalysisSummary[]> {
  return request(`/sessions/${encodeURIComponent(sessionId)}/analyses`)
}

export function getGapRanking(sessionId: string): Promise<GapRanking> {
  return request(`/sessions/${encodeURIComponent(sessionId)}/gaps`)
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
