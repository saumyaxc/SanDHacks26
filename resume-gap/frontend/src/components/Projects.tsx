import type { GapRecommendation, ResourceType } from '../api'

const RESOURCE_LABEL: Record<ResourceType, string> = {
  official_docs: 'Official docs',
  course: 'Course',
  tutorial: 'Tutorial',
  book: 'Book',
  video: 'Video',
  practice: 'Practice',
}

/** The 1-3 weekend projects and the starting resource for one gap. */
export function ProjectPlan({ rec }: { rec: GapRecommendation }) {
  return (
    <>
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
    </>
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
