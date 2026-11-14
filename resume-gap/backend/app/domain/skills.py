"""Skill normalization. Cross-JD aggregation groups by the canonical name,
so every alias of a skill must map to exactly one canonical string.

Rules:
- Keys are already-normalized (lowercase, single spaces).
- Values are canonical names and must NOT themselves be keys that map elsewhere.
- Unknown skills pass through as their normalized form.
- Ambiguous abbreviations (e.g. "tf" = terraform or tensorflow) are deliberately omitted.

Tech-focused for now; the cross-field section is a small seed, not full coverage.
"""

import re

ALIASES: dict[str, str] = {
    # Languages
    "js": "javascript",
    "ecmascript": "javascript",
    "ts": "typescript",
    "py": "python",
    "python3": "python",
    "golang": "go",
    "c sharp": "c#",
    "csharp": "c#",
    "cpp": "c++",
    # Frameworks / runtimes
    "react.js": "react",
    "reactjs": "react",
    "node": "node.js",
    "nodejs": "node.js",
    "vue.js": "vue",
    "vuejs": "vue",
    "next": "next.js",
    "nextjs": "next.js",
    "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn",
    # Infra / cloud
    "k8s": "kubernetes",
    "kube": "kubernetes",
    "amazon web services": "aws",
    "google cloud": "gcp",
    "google cloud platform": "gcp",
    "microsoft azure": "azure",
    "gh actions": "github actions",
    "ci cd": "ci/cd",
    "cicd": "ci/cd",
    "continuous integration": "ci/cd",
    # Data
    "postgres": "postgresql",
    "psql": "postgresql",
    "mongo": "mongodb",
    # Concepts
    "rest api": "rest",
    "rest apis": "rest",
    "restful": "rest",
    "restful api": "rest",
    "restful apis": "rest",
    "ml": "machine learning",
    "dl": "deep learning",
    "nlp": "natural language processing",
    "llm": "large language models",
    "llms": "large language models",
    "oop": "object-oriented programming",
    "dsa": "data structures and algorithms",
    # Cross-field seed
    "ms excel": "excel",
    "microsoft excel": "excel",
    "project management professional": "pmp",
    "certified public accountant": "cpa",
    "sfdc": "salesforce",
}

_WHITESPACE = re.compile(r"\s+")


def normalize_skill(raw: str) -> str:
    """'  K8s ' -> 'kubernetes'; 'Rust' -> 'rust'."""
    key = _WHITESPACE.sub(" ", raw.strip().lower()).strip(" .,;:")
    return ALIASES.get(key, key)
