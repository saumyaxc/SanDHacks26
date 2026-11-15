"""Canned-response client for tests and keyless local dev.

Responses are keyed by schema class name. A str value is returned every time;
a list value is consumed in order (use it to simulate bad-then-good output).
"""

import json

from pydantic import BaseModel

from .base import LLMClient, LLMError

# One self-consistent example: every bucket appears, and every evidence_id exists.
DEFAULT_RESPONSES: dict[str, str] = {
    "RequirementsExtraction": json.dumps(
        {
            "role_title": "Backend Engineer",
            "company": "Acme",
            "requirements": [
                {
                    "id": "req-1",
                    "skill": "Python",
                    "canonical_skill": "python",
                    "category": "technology",
                    "priority": "required",
                    "years_required": 3,
                    "jd_quote": "3+ years of professional experience with Python",
                },
                {
                    "id": "req-2",
                    "skill": "K8s",
                    "canonical_skill": "kubernetes",
                    "category": "technology",
                    "priority": "required",
                    "years_required": None,
                    "jd_quote": "Experience deploying services on Kubernetes (K8s)",
                },
                {
                    "id": "req-3",
                    "skill": "AWS",
                    "canonical_skill": "aws",
                    "category": "technology",
                    "priority": "preferred",
                    "years_required": None,
                    "jd_quote": "Familiarity with AWS is a plus",
                },
                {
                    "id": "req-4",
                    "skill": "PostgreSQL",
                    "canonical_skill": "postgresql",
                    "category": "technology",
                    "priority": "required",
                    "years_required": None,
                    "jd_quote": "Strong SQL skills, ideally PostgreSQL",
                },
                {
                    "id": "req-5",
                    "skill": "communication",
                    "canonical_skill": "communication",
                    "category": "soft_skill",
                    "priority": "preferred",
                    "years_required": None,
                    "jd_quote": "Clear written and verbal communication",
                },
            ],
            "eligibility": [
                {
                    "id": "elig-1",
                    "kind": "work_authorization",
                    "description": "Authorized to work in the US",
                    "jd_quote": "Must be authorized to work in the United States",
                }
            ],
        }
    ),
    "EvidenceExtraction": json.dumps(
        {
            "items": [
                {
                    "id": "ev-1",
                    "section": "experience",
                    "line": "Built REST APIs in Python and FastAPI serving 10k daily users",
                    "skills": [
                        {"skill": "Python", "canonical_skill": "python"},
                        {"skill": "FastAPI", "canonical_skill": "fastapi"},
                        {"skill": "REST APIs", "canonical_skill": "rest"},
                    ],
                },
                {
                    "id": "ev-2",
                    "section": "experience",
                    "line": "Deployed services to Google Cloud Run with Docker",
                    "skills": [
                        {"skill": "Google Cloud Run", "canonical_skill": "gcp"},
                        {"skill": "Docker", "canonical_skill": "docker"},
                    ],
                },
                {
                    "id": "ev-3",
                    "section": "skills",
                    "line": "Skills: Python, Postgres, Docker, Git",
                    "skills": [
                        {"skill": "Python", "canonical_skill": "python"},
                        {"skill": "Postgres", "canonical_skill": "postgresql"},
                        {"skill": "Docker", "canonical_skill": "docker"},
                        {"skill": "Git", "canonical_skill": "git"},
                    ],
                },
                {
                    "id": "ev-4",
                    "section": "experience",
                    "line": "Presented quarterly project results to a 40-person engineering org",
                    "skills": [{"skill": "Presented", "canonical_skill": "communication"}],
                },
            ]
        }
    ),
    "MatchDecisions": json.dumps(
        {
            "decisions": [
                {
                    "requirement_id": "req-1",
                    "bucket": "covered",
                    "evidence_id": "ev-1",
                    "rationale": "Python used directly in production work.",
                },
                {
                    "requirement_id": "req-2",
                    "bucket": "gap",
                    "evidence_id": None,
                    "rationale": "No Kubernetes or container orchestration mentioned.",
                },
                {
                    "requirement_id": "req-3",
                    "bucket": "transferable",
                    "evidence_id": "ev-2",
                    "rationale": "GCP deployment experience transfers to AWS.",
                },
                {
                    "requirement_id": "req-4",
                    "bucket": "underemphasized",
                    "evidence_id": "ev-3",
                    "rationale": "Postgres is only listed in skills, never shown in use.",
                },
                {
                    "requirement_id": "req-5",
                    "bucket": "covered",
                    "evidence_id": "ev-4",
                    "rationale": "Regular presentations to a large audience.",
                },
            ],
            "eligibility": [
                {
                    "eligibility_id": "elig-1",
                    "status": "unknown",
                    "evidence_id": None,
                    "rationale": "The resume does not state work authorization.",
                }
            ],
        }
    ),
    "GapRecommendationDrafts": json.dumps(
        {
            "recommendations": [
                {
                    "requirement_id": "req-2",
                    "projects": [
                        {
                            "title": "Run your FastAPI app on local Kubernetes",
                            "description": "Write a Deployment and Service manifest for an existing API, run it on minikube, and add a readiness probe.",
                            "estimated_hours": 6,
                        },
                        {
                            "title": "Zero-downtime deploys with rolling updates",
                            "description": "Ship two versions of the API with a rolling update and a ConfigMap, and document how you rolled back a bad release.",
                            "estimated_hours": 12,
                        },
                    ],
                    "resource_type": "tutorial",
                    "resource_title": "Kubernetes 'Hello Minikube' tutorial",
                    "resource_url": "https://kubernetes.io/docs/tutorials/hello-minikube/",
                },
                {
                    "requirement_id": "req-3",
                    "projects": [
                        {
                            "title": "Port a Cloud Run service to AWS",
                            "description": "Deploy the same Docker image to AWS App Runner and document the differences from Cloud Run.",
                            "estimated_hours": 6,
                        }
                    ],
                    "resource_type": "official_docs",
                    "resource_title": "AWS App Runner Developer Guide",
                    "resource_url": None,
                },
            ]
        }
    ),
}


# A job description containing every canned requirement quote, so stage 1's verbatim check
# passes in fake mode and in tests.
DEFAULT_JD_TEXT = "Backend Engineer at Acme\n" + "\n".join(
    [r["jd_quote"] for r in json.loads(DEFAULT_RESPONSES["RequirementsExtraction"])["requirements"]]
    + [e["jd_quote"] for e in json.loads(DEFAULT_RESPONSES["RequirementsExtraction"])["eligibility"]]
)


class FakeLLMClient(LLMClient):
    def __init__(self, responses: dict[str, str | list[str]] | None = None) -> None:
        source = DEFAULT_RESPONSES if responses is None else responses
        # Copy lists so popping queued responses never mutates the caller's data.
        self._responses: dict[str, str | list[str]] = {
            k: list(v) if isinstance(v, list) else v for k, v in source.items()
        }
        self.calls: list[tuple[str, str]] = []  # (schema name, prompt) for test assertions

    def _generate(self, prompt: str, schema: type[BaseModel]) -> str:
        name = schema.__name__
        self.calls.append((name, prompt))

        if name not in self._responses:
            raise LLMError(f"FakeLLMClient has no canned response for {name}")

        value = self._responses[name]
        if isinstance(value, str):
            return value
        if not value:
            raise LLMError(f"FakeLLMClient ran out of queued responses for {name}")
        return value.pop(0)
