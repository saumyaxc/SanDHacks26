import { useEffect, useRef, useState, type SubmitEvent } from 'react'
import {
  analyze,
  ApiError,
  deleteAnalysis,
  dismissGap,
  getAnalysis,
  getGapRanking,
  getSessionId,
  listAnalyses,
  MAX_INPUT_CHARS,
  restoreGap,
  type AnalysisResult,
  type AnalysisSummary,
  type GapRanking,
} from './api'
import { EmptyState } from './components/EmptyState'
import { History } from './components/History'
import { Loading } from './components/Loading'
import { Results } from './components/Results'
import { ResumeInput } from './components/ResumeInput'
import { TopGaps } from './components/TopGaps'
import { forgetSavedResume, loadSavedResume, saveResume, type SavedResume } from './savedResume'
import './App.css'

const sessionId = getSessionId()
const initialSaved = loadSavedResume()

export default function App() {
  const [jd, setJd] = useState('')
  // Returning users start with the resume they used last (remembered in this browser only).
  const [saved, setSaved] = useState<SavedResume | null>(initialSaved)
  const [resume, setResume] = useState(initialSaved?.text ?? '')
  const [resumeHint, setResumeHint] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [history, setHistory] = useState<AnalysisSummary[]>([])
  const [ranking, setRanking] = useState<GapRanking | null>(null)
  // True until the first history/ranking load finishes (the database may be waking up).
  const [sidebarLoading, setSidebarLoading] = useState(true)
  // After an analysis the inputs fold away so the sidebar has room for history and gaps.
  const [inputsOpen, setInputsOpen] = useState(true)
  const mainRef = useRef<HTMLElement>(null)

  // History and ranking are conveniences: if they fail, the main flow still works.
  function loadSidebar(isCancelled: () => boolean = () => false) {
    const history = listAnalyses(sessionId)
      .then((items) => !isCancelled() && setHistory(items))
      .catch(() => {})
    const gaps = getGapRanking(sessionId)
      .then((r) => !isCancelled() && setRanking(r))
      .catch(() => {})
    void Promise.all([history, gaps]).then(() => !isCancelled() && setSidebarLoading(false))
  }

  // Load this browser's past analyses once (fetch = external system, so an effect is right).
  useEffect(() => {
    let cancelled = false
    loadSidebar(() => cancelled)
    return () => {
      cancelled = true
    }
  }, [])

  // Tick the elapsed-seconds counter while a request is in flight.
  useEffect(() => {
    if (!loading) return
    const timer = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(timer)
  }, [loading])

  function scrollToMain() {
    // Only matters on narrow screens, where results sit below the form.
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    requestAnimationFrame(() =>
      mainRef.current?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' }),
    )
  }

  function showResult(r: AnalysisResult) {
    setResult(r)
    setInputsOpen(false)
    scrollToMain()
  }

  function onResumeUploaded(text: string, fileName: string) {
    setResume(text)
    setSaved(saveResume(text, fileName))
    setResumeHint(null)
  }

  function onResumeChange(text: string) {
    setResume(text)
    setResumeHint(null)
  }

  function onForgetResume() {
    forgetSavedResume()
    setSaved(null)
  }

  const savedLabel =
    saved && saved.text === resume
      ? `${saved.label}, saved ${new Date(saved.savedAt).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`
      : null

  async function onSubmit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setElapsed(0)
    setLoading(true)
    scrollToMain()
    try {
      const label = saved?.text === resume ? saved.label : 'pasted text'
      showResult(await analyze(sessionId, jd, resume, label))
      // Remember the resume that just worked, so next time starts with it.
      if (saved?.text !== resume) setSaved(saveResume(resume, label))
      loadSidebar()
    } catch (err) {
      setError(describe(err))
    } finally {
      setLoading(false)
    }
  }

  // Start over for a new job: clear the old job description and result, keep the resume.
  function startNewAnalysis() {
    setJd('')
    setResult(null)
    setError(null)
    setResumeHint(null)
    setInputsOpen(true)
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    window.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' })
  }

  async function onSelectHistory(id: string) {
    setError(null)
    try {
      const r = await getAnalysis(id)
      // Always replace the job box, so it never shows a different job than the one on screen.
      // Analyses saved before JDs were stored have none.
      setJd(r.jd_text)
      setResumeHint(null)
      showResult(r)
    } catch (err) {
      setError(describe(err))
    }
  }

  // Same job, different resume: reopen the inputs with this job's description filled in.
  function tryAnotherResume() {
    if (!result?.jd_text) return
    setJd(result.jd_text)
    setInputsOpen(true)
    setResumeHint('Upload or paste the resume you want to compare against this job, then hit Analyze.')
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    window.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' })
  }

  async function onDeleteJob(ids: string[]) {
    setError(null)
    try {
      await Promise.all(ids.map((id) => deleteAnalysis(sessionId, id)))
      if (result && ids.includes(result.id)) startNewAnalysis()
      loadSidebar()
    } catch (err) {
      setError(describe(err))
    }
  }

  async function onDismissGap(skill: string) {
    try {
      await dismissGap(sessionId, skill)
      loadSidebar()
    } catch (err) {
      setError(describe(err))
    }
  }

  async function onRestoreGap(skill: string) {
    try {
      await restoreGap(sessionId, skill)
      loadSidebar()
    } catch (err) {
      setError(describe(err))
    }
  }

  const tooLong = jd.length > MAX_INPUT_CHARS || resume.length > MAX_INPUT_CHARS
  // Home = nothing open yet. Past analyses and Learn next then sit beside the form, both visible.
  const home = !result && !loading

  const panels = (
    <>
      {sidebarLoading && (
        <div className="sidebar-loading" role="status" aria-live="polite">
          <p className="small muted">
            <span className="spinner" aria-hidden="true" /> Loading your past analyses…
          </p>
          <span className="sk sk-row" aria-hidden="true" />
          <span className="sk sk-row" aria-hidden="true" />
        </div>
      )}
      <History items={history} activeId={result?.id ?? null} onSelect={onSelectHistory} onDeleteJob={onDeleteJob} />
      <TopGaps ranking={ranking} onOpenAnalysis={onSelectHistory} onDismiss={onDismissGap} onRestore={onRestoreGap} />
    </>
  )
  const canSubmit = jd.trim() !== '' && resume.trim() !== '' && !tooLong && !loading

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>resume-gap</h1>
          <p className="muted">
            See which job requirements your resume backs up — with the exact line as proof — and what to build for the
            rest.
          </p>
        </div>
        {(result || loading) && (
          <button type="button" className="button-primary button-new" onClick={startNewAnalysis} disabled={loading}>
            + New analysis
          </button>
        )}
      </header>

      <div className="layout">
        <aside className="sidebar">
          {inputsOpen ? (
            <form className="inputs" onSubmit={onSubmit}>
              <TextBox label="Job description" value={jd} onChange={setJd} placeholder="Paste the full job posting" />
              <ResumeInput
                value={resume}
                onChange={onResumeChange}
                onUploaded={onResumeUploaded}
                savedLabel={savedLabel}
                onForget={onForgetResume}
                hint={resumeHint}
              />
              <button type="submit" className="button-primary" disabled={!canSubmit}>
                {loading ? 'Analyzing…' : 'Analyze'}
              </button>
              {result && !loading && (
                <button type="button" className="button-link" onClick={() => setInputsOpen(false)}>
                  Hide inputs
                </button>
              )}
            </form>
          ) : (
            <div className="inputs-collapsed">
              <div>
                <p className="small muted">Inputs</p>
                <p className="small">
                  {jd.trim() ? 'Job ✓' : 'Job: not saved'} · {resume.trim() ? 'Resume ✓' : 'Resume: not loaded'}
                </p>
              </div>
              <button type="button" className="button-small" onClick={() => setInputsOpen(true)}>
                Edit inputs
              </button>
            </div>
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {/* On the home view these panels sit beside the form instead (see <main>). */}
          {!home && panels}
        </aside>

        <main className="main" ref={mainRef}>
          {loading ? (
            <Loading elapsed={elapsed} />
          ) : result ? (
            // key: a different analysis starts with fresh tabs and open sections.
            <Results
              key={result.id}
              result={result}
              versions={history.filter((h) => h.job_key === result.job_key)}
              onSelectVersion={onSelectHistory}
              onTryAnotherResume={tryAnotherResume}
            />
          ) : sidebarLoading || history.length > 0 ? (
            // Home for returning users: everything visible at once, no scrolling.
            <div className="home">
              <div className="home-panels">{panels}</div>
              <details className="home-how">
                <summary>How it works</summary>
                <EmptyState />
              </details>
            </div>
          ) : (
            <EmptyState />
          )}
        </main>
      </div>

      <footer className="app-footer">
        This analysis is generated by AI and can be wrong. Double-check every match, quote, and suggestion against
        your resume and the job posting before relying on it.
      </footer>
    </div>
  )
}

function TextBox({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder: string
}) {
  const over = value.length > MAX_INPUT_CHARS
  return (
    <label className="textbox">
      <span className="textbox-label">{label}</span>
      <textarea value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} rows={6} />
      {over && <TooLong />}
    </label>
  )
}

function TooLong() {
  return (
    <p className="upload-note error" role="alert">
      This is over {MAX_INPUT_CHARS.toLocaleString()} characters. Trim it down (e.g. remove the company boilerplate) to
      analyze it.
    </p>
  )
}

function describe(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return 'The AI model is busy right now (rate limit). Wait about a minute and try again.'
    return err.message
  }
  return 'Something went wrong. Please try again.'
}
