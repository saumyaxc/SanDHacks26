from enum import StrEnum


class Bucket(StrEnum):
    """How well the resume covers one JD requirement."""

    COVERED = "covered"  # clearly demonstrated in experience/projects
    UNDEREMPHASIZED = "underemphasized"  # present but buried, vague, or only in a skills list
    TRANSFERABLE = "transferable"  # not present, but an adjacent skill is (e.g. GCP for AWS)
    GAP = "gap"  # no supporting evidence at all


class Priority(StrEnum):
    REQUIRED = "required"
    PREFERRED = "preferred"


class SkillCategory(StrEnum):
    """Field-agnostic on purpose so non-tech JDs still classify sensibly."""

    # Named things a resume line either names or doesn't: Python, React, Docker, AWS, Excel, Figma.
    TECHNOLOGY = "technology"
    # Practices, methods, knowledge areas: CI/CD, debugging, data visualization, financial modeling.
    CONCEPT = "concept"
    DOMAIN_KNOWLEDGE = "domain_knowledge"  # fintech, healthcare, e-commerce
    SOFT_SKILL = "soft_skill"  # communication, leadership — things a resume line can show
    CREDENTIAL = "credential"  # degree, certification, license
    # Interest, passion, mindset ("passion for Pinterest", "growth mindset"). Not resume-provable:
    # shown separately as cover-letter/interview material, never scored or ranked as a gap.
    TRAIT = "trait"


# How each kind of requirement is treated — the one place this is decided:
#   technology / concept / domain_knowledge -> a real gap if nothing supports it (weekend project);
#       if the work is there but described differently, it's a rewrite instead.
#   credential -> checked, never a project (you can't build a degree in a weekend).
#   soft_skill / trait -> "for your cover letter & interview": shown with any supporting line,
#       but never a gap, never scored, ranked, or turned into a project. Communication,
#       multitasking, prioritization, and passion are judged by people, not resume lines.
INTERVIEW_CATEGORIES = frozenset({SkillCategory.SOFT_SKILL, SkillCategory.TRAIT})


class ResumeSection(StrEnum):
    EXPERIENCE = "experience"
    PROJECT = "project"
    EDUCATION = "education"
    SKILLS = "skills"
    OTHER = "other"


class ResourceType(StrEnum):
    OFFICIAL_DOCS = "official_docs"
    COURSE = "course"
    TUTORIAL = "tutorial"
    BOOK = "book"
    VIDEO = "video"
    PRACTICE = "practice"  # hands-on practice platform or exercises


class EligibilityKind(StrEnum):
    """Hard requirements about the candidate, not skills: failing one means don't apply."""

    DEGREE_LEVEL = "degree_level"  # "pursuing a Bachelor's", "PhD required"
    ENROLLMENT = "enrollment"  # "currently enrolled", "returning to school after the internship"
    GRADUATION_WINDOW = "graduation_window"  # "graduating between Dec 2026 and Jun 2027"
    WORK_AUTHORIZATION = "work_authorization"  # never inferred from a resume
    OTHER = "other"


class EligibilityStatus(StrEnum):
    MET = "met"
    NOT_MET = "not_met"
    UNKNOWN = "unknown"  # the resume doesn't say; the candidate must check
