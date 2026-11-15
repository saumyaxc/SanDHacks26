"""Stage 2: resume text -> evidence lines that verifiably exist in the resume."""

import logging
from pathlib import Path

from app.domain.quotes import normalize_for_quote, quote_in_text
from app.domain.schemas import EvidenceExtraction, EvidenceItem, ExtractEvidenceInput, SkillMention
from app.domain.skills import skill_vocabulary
from app.llm.base import LLMClient, LLMError

log = logging.getLogger(__name__)

_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "extract_evidence.md").read_text(
    encoding="utf-8"
)


def extract_evidence(data: ExtractEvidenceInput, llm: LLMClient) -> EvidenceExtraction:
    # Resume goes last so its text is never scanned for placeholders.
    prompt = _PROMPT.replace("{{KNOWN_SKILLS}}", ", ".join(skill_vocabulary(data.known_skills))).replace(
        "{{RESUME_TEXT}}", data.resume_text
    )
    raw = llm.complete_json(prompt, EvidenceExtraction)
    return _clean(raw, data.resume_text)


def _clean(extraction: EvidenceExtraction, resume_text: str) -> EvidenceExtraction:
    """Drop lines not found verbatim in the resume, drop duplicate lines, dedupe skills, renumber.

    Raises LLMError if nothing survives: the model returned no usable evidence.
    """
    seen_lines: set[str] = set()
    items: list[EvidenceItem] = []
    for item in extraction.items:
        if not quote_in_text(item.line, resume_text):
            log.warning("dropping evidence not found verbatim in resume: %r", item.line[:100])
            continue
        key = normalize_for_quote(item.line)
        if key in seen_lines:
            continue
        seen_lines.add(key)
        items.append(item.model_copy(update={"skills": _dedupe_skills(item.skills)}))

    if not items:
        raise LLMError("no extracted evidence line was found verbatim in the resume")
    return EvidenceExtraction(
        items=[item.model_copy(update={"id": f"ev-{i}"}) for i, item in enumerate(items, start=1)]
    )


def _dedupe_skills(skills: list[SkillMention]) -> list[SkillMention]:
    seen: set[str] = set()
    out: list[SkillMention] = []
    for s in skills:
        if s.canonical_skill and s.canonical_skill not in seen:
            seen.add(s.canonical_skill)
            out.append(s)
    return out
