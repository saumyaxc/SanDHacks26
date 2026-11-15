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
    SOFT_SKILL = "soft_skill"  # communication, leadership
    CREDENTIAL = "credential"  # degree, certification, license


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
