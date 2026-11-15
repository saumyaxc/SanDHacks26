"""Strip personal contact details from RESUME text before it reaches the LLM or storage.

Only resumes go through this; job descriptions are never redacted (their locations,
company links, etc. are part of the job).

Deterministic on purpose: an LLM can't leak what it never receives.

Removed anywhere in the resume: emails, phone numbers, web links (a repo URL still
contains a username).

Removed ONLY in the header (lines above the first section heading, where contact info lives):
- the name line (first non-empty line, if it looks like a name)
- a line that held contact details (whatever is left of it)
- a line that is exactly a home location, "City, ST" or "City, ST 92093"

Locations anywhere else are kept: "Software Intern, Acme — San Diego, CA" is evidence context.

Heuristic limits (accepted): a name written somewhere unusual, or a street address in the
body, can survive. The UI shows the cleaned text so the user can check before analyzing.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from .reflow import reflow

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# 10-11 digit phone numbers with common separators: (858) 555-1234, +1 858.555.1234, 8585551234
_PHONE = re.compile(r"(?<![\w])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?![\w])")
# Links stop before closing brackets/quotes so "(https://x.com/a)" leaves "()" for cleanup.
_URL_TAIL = r"[^\s)\]}>\"']*"
_URL = re.compile(
    rf"(?:https?://|www\.){_URL_TAIL}"
    rf"|\b(?:[\w-]+\.)*(?:linkedin|github|gitlab|behance|dribbble|medium|substack|x|twitter)\.com/{_URL_TAIL}",
    re.IGNORECASE,
)
_HOME_LOCATION = re.compile(r"^[A-Z][a-zA-Z .'-]+,\s*[A-Z]{2}(?:\s+\d{5})?$")
_NAME_WORD = re.compile(r"^[A-Z][a-zA-Z.'’-]*$")
_HEADINGS = {
    "summary", "profile", "objective", "about", "education", "experience", "work experience",
    "professional experience", "employment", "projects", "skills", "technical skills",
    "certifications", "awards", "publications", "leadership", "activities", "coursework",
}  # fmt: skip
_ONLY_SEPARATORS = re.compile(r"^[\s|•·,;/–—-]*$")


@dataclass
class Redaction:
    text: str
    removed: list[str] = field(default_factory=list)  # e.g. ["name", "email", "phone", "link"]


def redact_resume(text: str) -> Redaction:
    text = unicodedata.normalize("NFKC", text)  # also fixes PDF ligatures like "ﬁ" -> "fi"
    text = reflow(text)  # one-word-per-line pastes -> real lines, so headers/bullets are findable
    removed: list[str] = []
    lines = text.splitlines()
    first_heading = next((i for i, line in enumerate(lines) if _is_heading(line)), None)

    out: list[str] = []
    name_checked = False
    for i, line in enumerate(lines):
        cleaned, kinds = _scrub(line)
        removed += kinds

        # Header rules only apply when there IS a heading to bound the header.
        if first_heading is not None and i < first_heading and line.strip():
            if not name_checked:
                name_checked = True
                if _looks_like_name(cleaned):
                    removed.append("name")
                    continue
            if _HOME_LOCATION.match(cleaned.strip()):
                removed.append("location")
                continue
            if kinds:
                continue  # a contact line: drop whatever separators/labels are left

        if kinds and _ONLY_SEPARATORS.match(cleaned):
            continue  # a body line that was nothing but contact info
        out.append(cleaned)

    return Redaction(text="\n".join(out).strip("\n"), removed=removed)


def _scrub(line: str) -> tuple[str, list[str]]:
    kinds: list[str] = []
    for kind, pattern in (("email", _EMAIL), ("link", _URL), ("phone", _PHONE)):
        line, n = pattern.subn("", line)
        kinds += [kind] * n
    if kinds:
        line = re.sub(r"\(\s*\)", "", line)  # "(github.com/x/repo)" -> ""
        line = re.sub(r"[ \t]{2,}", " ", line).rstrip(" |,;:-–—")
    return line, kinds


def _is_heading(line: str) -> bool:
    return line.strip().strip(":").lower() in _HEADINGS


def _looks_like_name(line: str) -> bool:
    words = line.strip().split()
    return 2 <= len(words) <= 4 and all(_NAME_WORD.match(w) for w in words) and not _is_heading(line)


def describe_removed(removed: list[str]) -> str:
    """["name", "email", "link", "link"] -> "name, email, 2 links"."""
    parts = []
    for kind in ("name", "email", "phone", "location", "link"):
        n = removed.count(kind)
        if n:
            parts.append(kind if n == 1 else f"{n} {kind}s")
    return ", ".join(parts)
