import { BUCKETS } from '../api'
import { BUCKET_INFO } from '../buckets'

const HOW_IT_WORKS = [
  { title: 'Paste the job', text: 'We pull out every skill, tool, and credential it asks for, and which are required.' },
  { title: 'Add your resume', text: 'Upload a PDF or paste text. Your name and contact details are removed first.' },
  {
    title: 'Get the honest picture',
    text: 'Each requirement is matched to the exact line on your resume that proves it — or marked as a gap.',
  },
  { title: 'Close the gaps', text: 'Rewrites that only rephrase what you did, plus weekend projects for what is missing.' },
]

export function EmptyState() {
  return (
    <div className="empty-state">
      <section>
        <h2>How it works</h2>
        <ol className="how-steps">
          {HOW_IT_WORKS.map((step, i) => (
            <li key={step.title}>
              <span className="how-num" aria-hidden="true">
                {i + 1}
              </span>
              <div>
                <h3>{step.title}</h3>
                <p className="muted">{step.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h2>What the results mean</h2>
        <ul className="legend">
          {BUCKETS.map((b) => (
            <li key={b}>
              <span className={`chip chip-${b}`}>{BUCKET_INFO[b].label}</span>
              <span className="muted">{BUCKET_INFO[b].blurb}</span>
            </li>
          ))}
        </ul>
      </section>

      <p className="muted small">
        Your text is sent to Google's Gemini API to run the analysis. Name, email, phone, and profile links are stripped
        before it leaves this app.
      </p>
    </div>
  )
}
