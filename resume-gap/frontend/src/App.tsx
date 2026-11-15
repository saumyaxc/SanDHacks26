import { useEffect, useRef, useState, type SubmitEvent } from 'react'
import {
  analyze,
  ApiError,
  getAnalysis,
  getGapRanking,
  getSessionId,
  listAnalyses,
  MAX_INPUT_CHARS,
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
import './App.css'

const sessionId = getSessionId()

export default function App() {
  const [jd, setJd] = useState('')
  const [resume, setResume] = useState('')
  const [loading, setLoading] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [history, setHistory] = useState<AnalysisSummary[]>([])
  const [ranking, setRanking] = useState<GapRanking | null>(null)
  // After an analysis the inputs fold away so the sidebar has room for history and gaps.
  const [inputsOpen, setInputsOpen] = useState(true)
  const mainRef = useRef<HTMLElement>(null)

  // History and ranking are conveniences: if they fail, the main flow still works.
  function loadSidebar(isCancelled: () => boolean = () => false) {
    listAnalyses(sessionId)
      .then((items) => !isCancelled() && setHistory(items))
      .catch(() => {})
    getGapRanking(sessionId)
      .then((r) => !isCancelled() && setRanking(r))
      .catch(() => {})
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

  async function onSubmit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setElapsed(0)
    setLoading(true)
    scrollToMain()
    try {
      showResult(await analyze(sessionId, jd, resume))
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
    setInputsOpen(true)
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    window.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' })
  }

  async function onSelectHistory(id: string) {
    setError(null)
    try {
      showResult(await getAnalysis(id))
    } catch (err) {
      setError(describe(err))
    }
  }

  const tooLong = jd.length > MAX_INPUT_CHARS || resume.length > MAX_INPUT_CHARS
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
              <ResumeInput value={resume} onChange={setResume} />
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
                  {jd.trim() ? `Job: ${jd.length.toLocaleString()} chars` : 'Job: from history'} ·{' '}
                  {resume.trim() ? `Resume: ${resume.length.toLocaleString()} chars` : 'Resume: from history'}
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
          <TopGaps ranking={ranking} onOpen={onSelectHistory} />
          <History items={history} activeId={result?.id ?? null} onSelect={onSelectHistory} />
        </aside>

        <main className="main" ref={mainRef}>
          {loading ? (
            <Loading elapsed={elapsed} />
          ) : result ? (
            // key: a different analysis starts with fresh tabs and open sections.
            <Results key={result.id} result={result} />
          ) : (
            <EmptyState />
          )}
        </main>
      </div>
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
      <span className="textbox-label">
        {label}
        <span className={`counter ${over ? 'over' : ''}`}>
          {value.length.toLocaleString()} / {MAX_INPUT_CHARS.toLocaleString()}
        </span>
      </span>
      <textarea value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} rows={8} />
    </label>
  )
}

function describe(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return 'The AI model is busy right now (rate limit). Wait about a minute and try again.'
    return err.message
  }
  return 'Something went wrong. Please try again.'
}
