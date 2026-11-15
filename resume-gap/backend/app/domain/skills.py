"""Skill normalization. Cross-JD aggregation groups by the canonical name.

How a canonical name is produced:
1. The LLM proposes a standard name, reusing one from the known-skills list when it fits.
2. normalize_skill() cleans formatting (case, hyphens, punctuation, whitespace).
3. ALIASES overrides the result for abbreviations the LLM may leave as-is.

ALIASES is a small safety net, not the main mechanism — don't grow it per JD.

Invariants (tested in tests/test_skills.py):
- normalize_skill(v) == v for every alias value (canonical names are stable).
- Ambiguous abbreviations (e.g. "tf" = terraform or tensorflow) are omitted.
"""

import re

from .quotes import normalize_for_quote

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
    "ai": "artificial intelligence",
    "oop": "object oriented programming",
    "dsa": "data structures and algorithms",
    "data structures": "data structures and algorithms",
    "algorithms": "data structures and algorithms",
    # Soft skills / work styles (one name each; see SOFT_SKILLS)
    "written communication": "communication",
    "verbal communication": "communication",
    "written and verbal communication": "communication",
    "communication skills": "communication",
    "problem solving skills": "problem solving",
    "ambiguity": "navigating ambiguity",
    "comfort with ambiguity": "navigating ambiguity",
    "dealing with ambiguity": "navigating ambiguity",
    "multitasking": "prioritization",
    "multi tasking": "prioritization",
    "prioritizing": "prioritization",
    "team work": "teamwork",
    "collaborative": "collaboration",
    # Cross-field seed
    "ms excel": "excel",
    "microsoft excel": "excel",
    "project management professional": "pmp",
    "certified public accountant": "cpa",
    "sfdc": "salesforce",
}

_WHITESPACE = re.compile(r"\s+")


def normalize_skill(raw: str) -> str:
    """'  K8s ' -> 'kubernetes'; 'Problem-Solving' -> 'problem solving'; 'Rust' -> 'rust'."""
    key = raw.strip().lower().replace("-", " ")
    key = _WHITESPACE.sub(" ", key).strip(" .,;:")
    return ALIASES.get(key, key)


def known_canonical_skills() -> set[str]:
    """Seed vocabulary shown to the LLM so it reuses existing canonical names."""
    return set(ALIASES.values()) | SOFT_SKILLS


def skill_vocabulary(extra: list[str]) -> list[str]:
    """Seed vocabulary plus caller-supplied skills (e.g. from past analyses), normalized and sorted."""
    return sorted(known_canonical_skills() | {normalize_skill(s) for s in extra if s.strip()})


def skill_names(skill: str, canonical: str) -> set[str]:
    """Every way a line might name this skill: raw, canonical, and alias spellings."""
    names = {canonical, normalize_skill(skill), skill.strip().lower()}
    return names | {alias for alias, value in ALIASES.items() if value == canonical}


def text_names_any(text: str, names: set[str]) -> bool:
    """Whole-term match after quote normalization.

    "go" must not match "going", and "c" must not match "c++" or "c#";
    terms that contain symbols ("c++", "node.js", "ci/cd") still match.
    """
    norm = normalize_for_quote(text)
    for name in names:
        term = normalize_for_quote(name)
        if term and re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9+#])", norm):
            return True
    return False


# Category nouns: a skill named with one of these is a kind of thing ("search systems",
# "AI coding tools", "backend services"), not one named product. No resume line contains
# that phrase literally, so it must be judged like a concept, never by name matching.
_GENERIC_NOUNS = frozenset(
    {
        "tool", "tools", "system", "systems", "service", "services", "platform", "platforms",
        "framework", "frameworks", "library", "libraries", "database", "databases",
        "language", "languages", "technology", "technologies", "infrastructure",
        "application", "applications", "stack", "stacks", "solution", "solutions",
        "pipeline", "pipelines", "architecture", "architectures", "workflow", "workflows",
        "development", "engineering", "concepts", "fundamentals",
        "api", "apis", "microservice", "microservices", "backend", "frontend", "cloud", "web", "mobile",
        "programming", "scripting", "testing", "design", "analysis", "analytics", "modeling",
        "algorithms", "structures", "data", "networking", "networks", "protocols", "security", "apps",
    }
)  # fmt: skip


def is_named_product(canonical_skill: str) -> bool:
    """True for one specific named thing (python, react, postgresql, aws, power bi);
    False for a kind of thing (search systems, ai coding tools, relational databases)."""
    return not (set(canonical_skill.lower().split()) & _GENERIC_NOUNS)


# Universal soft skills and work styles. A safety net like ALIASES: whatever category stage 1
# gives them, these are interview material, never resume gaps (see enums.INTERVIEW_CATEGORIES).
# Behaviors only — no technical skills belong here.
SOFT_SKILLS = frozenset(
    {
        "communication", "teamwork", "collaboration", "leadership", "mentoring", "problem solving",
        "critical thinking", "analytical thinking", "navigating ambiguity", "adaptability",
        "prioritization", "time management", "attention to detail", "organization", "ownership",
        "initiative", "accountability", "curiosity", "creativity", "growth mindset",
        "self motivation", "work ethic", "interpersonal skills", "stakeholder management",
        "presentation skills", "empathy", "learning agility", "willingness to learn",
    }
)  # fmt: skip


def is_soft_skill(canonical_skill: str) -> bool:
    return canonical_skill in SOFT_SKILLS


def display_name(canonical_skill: str) -> str:
    """'navigating ambiguity' -> 'Navigating ambiguity' (consistent soft-skill labels)."""
    return canonical_skill[:1].upper() + canonical_skill[1:]
