// The pipeline doesn't stream progress, so steps advance on typical timings.
// They're the real stages in the real order; only the timing is estimated.
const STEPS: { at: number; label: string }[] = [
  { at: 0, label: 'Reading the job description' },
  { at: 3, label: 'Pulling evidence lines from your resume' },
  { at: 8, label: 'Matching each requirement to your exact lines' },
  { at: 13, label: 'Writing rewrites and weekend projects' },
  { at: 19, label: 'Checking resource links' },
]
const SLOW_AFTER_SECONDS = 30

export function Loading({ elapsed }: { elapsed: number }) {
  const current = STEPS.findLastIndex((s) => elapsed >= s.at)
  return (
    <div className="loading" role="status" aria-live="polite">
      <div className="scan-doc" aria-hidden="true">
        <span className="scan-line w90 c-covered" />
        <span className="scan-line w70 c-under" />
        <span className="scan-line w80 c-covered" />
        <span className="scan-line w60 c-transfer" />
        <span className="scan-line w75 c-gap" />
        <span className="scan-line w50 c-covered" />
        <span className="scan-beam" />
      </div>

      <ol className="steps">
        {STEPS.map((step, i) => (
          <li key={step.label} className={i < current ? 'done' : i === current ? 'active' : ''}>
            <span className="step-dot" aria-hidden="true" />
            {step.label}
          </li>
        ))}
      </ol>
      <p className="muted small">
        {elapsed >= SLOW_AFTER_SECONDS
          ? 'Taking longer than usual: the AI model is busy. Hang tight.'
          : `${elapsed}s · usually 10–20 seconds`}
      </p>

      <div className="skeletons" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <div key={i} className="skeleton-card">
            <span className="sk sk-title" />
            <span className="sk sk-quote" />
            <span className="sk sk-text" />
          </div>
        ))}
      </div>
    </div>
  )
}
