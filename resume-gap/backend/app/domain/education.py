"""Read degree level and dates from education evidence lines — in code, not by the LLM.

Date arithmetic is where the model kept slipping (judging a finished Bachelor's instead of
the in-progress Master's), so this computes a plain timeline the eligibility check is given:

    ev-3 | master's | Sep 2026 – Jun 2028 | in progress (current program)
    ev-4 | bachelor's | Sep 2022 – Jun 2026 | completed

Understands "Sept. 2022 – Jun. 2026", "2021 - 2025", "Aug 2024 – Present", "Expected May 2027",
"Fall 2027", and a lone year ("B.S. Biology, 2019" = graduated 2019). When dates sit on a
school line and the level on the next/previous line, the two are paired.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from .enums import ResumeSection
from .schemas import EvidenceItem

Level = Literal["doctorate", "master's", "bachelor's", "associate"]
Status = Literal["completed", "in progress", "unknown"]

# Most specific first: "Master of Science" must not fall through to a bachelor's pattern.
_LEVELS: list[tuple[Level, re.Pattern[str]]] = [
    ("doctorate", re.compile(r"\bph\.?\s?d\b|\bdoctor(ate|al)?\b|\bd\.?phil\b", re.I)),
    ("master's", re.compile(r"\bmaster'?s?\b|\bm\.?\s?s\.?(?=[\s,]|$)|\bm\.?s\.?c\b|\bm\.?a\.?(?=[\s,]|$)|\bm\.?eng\b|\bmba\b", re.I)),
    ("bachelor's", re.compile(r"\bbachelor'?s?\b|\bb\.?\s?s\.?(?=[\s,]|$)|\bb\.?s\.?c\b|\bb\.?a\.?(?=[\s,]|$)|\bb\.?eng\b|\bundergrad", re.I)),
    ("associate", re.compile(r"\bassociate'?s?\s+(of|degree|in)\b", re.I)),
]
_LEVEL_RANK = {"associate": 1, "bachelor's": 2, "master's": 3, "doctorate": 4}

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "spring": 5, "summer": 8, "fall": 12, "autumn": 12, "winter": 3,
}  # fmt: skip
_DATE = re.compile(
    r"(?:\b(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|spring|summer|fall|autumn|winter)[a-z]*\.?\s*)?"
    r"\b(?P<year>(?:19|20)\d{2})\b",
    re.I,
)
_PRESENT = re.compile(r"\b(present|current|now|ongoing)\b", re.I)
_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

YearMonth = tuple[int, int]


@dataclass
class Program:
    evidence_id: str
    level: Level
    start: YearMonth | None
    end: YearMonth | None  # None with ongoing=True means "Present"
    ongoing: bool
    status: Status
    current: bool = False  # the in-progress program the candidate is applying from


def education_timeline(items: list[EvidenceItem], today: date) -> list[Program]:
    edu = [i for i in items if i.section == ResumeSection.EDUCATION]
    parsed = [(item, _level(item.line), _dates(item.line)) for item in edu]

    programs: list[Program] = []
    for idx, (item, level, dates) in enumerate(parsed):
        if level is None:
            continue
        if dates is None:  # dates may sit on the neighboring school line
            for j in (idx - 1, idx + 1):
                if 0 <= j < len(parsed) and parsed[j][1] is None and parsed[j][2] is not None:
                    dates = parsed[j][2]
                    break
        start, end, ongoing = dates if dates else (None, None, False)
        programs.append(
            Program(item.id, level, start, end, ongoing, _status(end, ongoing, today, has_dates=dates is not None))
        )

    in_progress = [p for p in programs if p.status == "in progress"]
    if in_progress:
        max(in_progress, key=lambda p: (_LEVEL_RANK[p.level], p.end or (9999, 12))).current = True
    return programs


def format_timeline(programs: list[Program]) -> str:
    if not programs:
        return "(no degree lines found)"
    lines = []
    for p in programs:
        span = f"{_fmt(p.start) or '?'} – {'Present' if p.ongoing else _fmt(p.end) or '?'}"
        note = " (current program)" if p.current else ""
        lines.append(f"{p.evidence_id} | {p.level} | {span} | {p.status}{note}")
    return "\n".join(lines)


def _level(line: str) -> Level | None:
    for level, pattern in _LEVELS:
        if pattern.search(line):
            return level
    return None


def _dates(line: str) -> tuple[YearMonth | None, YearMonth | None, bool] | None:
    found = [(int(m["year"]), _month(m["mon"])) for m in _DATE.finditer(line)]
    ongoing = bool(_PRESENT.search(line))
    if not found:
        return None
    if len(found) >= 2 or ongoing:
        start = _ym(found[0], default_month=9)
        end = None if ongoing else _ym(found[-1], default_month=6)
        return start, end, ongoing
    # A single date is the (expected) graduation date.
    return None, _ym(found[0], default_month=6), False


def _month(token: str | None) -> int | None:
    if not token:
        return None
    key = token.lower()
    return _MONTHS.get(key[:3]) or _MONTHS.get(key)  # "Sept." -> sep; "Fall" -> fall


def _ym(found: tuple[int, int | None], default_month: int) -> YearMonth:
    year, month = found
    return year, month or default_month


def _status(end: YearMonth | None, ongoing: bool, today: date, has_dates: bool) -> Status:
    if ongoing:
        return "in progress"
    if not has_dates or end is None:
        return "unknown"
    return "in progress" if end >= (today.year, today.month) else "completed"


def _fmt(ym: YearMonth | None) -> str | None:
    return f"{_MONTH_NAMES[ym[1] - 1]} {ym[0]}" if ym else None


# ---------- degree-level rules, decided in code ----------
#
# Two different kinds of rule look alike:
#   qualification:  "Bachelor's degree required", "BS or higher"  -> a higher degree meets it
#   student status: "pursuing a BS", "rising senior", "undergraduate", "currently enrolled in
#                   a Master's"                                    -> your CURRENT program must
#                                                                     be that level; an MS student
#                                                                     is not a rising senior.

_RULE_LEVELS: list[tuple[Level, re.Pattern[str]]] = [
    ("doctorate", re.compile(r"\bph\.?\s?d\b|\bdoctor(ate|al)?\b", re.I)),
    ("master's", re.compile(r"\bmaster'?s?\b|\bm\.?\s?s\.?(?=[\s,/)]|$)|\bmba\b|\bgraduate\s+(student|degree|program|school)\b", re.I)),
    (
        "bachelor's",
        re.compile(
            r"\bbachelor'?s?\b|\bb\.?\s?s\.?(?=[\s,/)]|$)|\bb\.?a\.?(?=[\s,/)]|$)|\bundergrad(uate)?\b"
            r"|\brising\s+(sophomore|junior|senior)\b|\b(sophomore|junior|senior)\s+(year|standing)\b",
            re.I,
        ),
    ),
]
_ADVANCED = re.compile(r"\badvanced\s+degree\b", re.I)
_OR_HIGHER = re.compile(r"\bor\s+(higher|above|advanced|graduate|beyond)\b|\bat\s+least\b|\bminimum\b", re.I)
_STUDENT_STATUS = re.compile(
    r"\b(pursuing|enrolled|enrollment|currently|rising|candidates?\s+only|students?|undergrad(uate)?|returning)\b", re.I
)


def judge_degree_rule(
    text: str, programs: list[Program]
) -> tuple[Literal["met", "not_met"], str, str] | None:
    """Decide a degree-level rule from the parsed timeline: (status, rationale, evidence_id),
    or None if the rule's wording or the resume is unclear."""
    allowed = {level for level, pattern in _RULE_LEVELS if pattern.search(text)}
    if _ADVANCED.search(text):
        allowed |= {"master's", "doctorate"}
    if not allowed:
        return None
    if _OR_HIGHER.search(text):
        floor = min(_LEVEL_RANK[level] for level in allowed)
        allowed |= {level for level, rank in _LEVEL_RANK.items() if rank >= floor}
    wanted = _describe(allowed)

    if _STUDENT_STATUS.search(text):
        current = next((p for p in programs if p.current), None)
        if current is None:
            return None  # no in-progress program found: let the LLM / the candidate judge
        span = f"{_fmt(current.start) or '?'} – {'Present' if current.ongoing else _fmt(current.end) or '?'}"
        if current.level in allowed:
            return (
                "met",
                f"The job wants current {wanted} students, and you're in a {current.level} program ({span}).",
                current.evidence_id,
            )
        return (
            "not_met",
            f"The job wants current {wanted} students, but your current program is a {current.level} ({span}).",
            current.evidence_id,
        )

    # A qualification: any degree at or above the lowest level asked for meets it.
    floor = min(_LEVEL_RANK[level] for level in allowed)
    best = max(programs, key=lambda p: _LEVEL_RANK[p.level], default=None)
    if best is not None and _LEVEL_RANK[best.level] >= floor:
        return "met", f"The job asks for a {wanted} degree, and your resume shows a {best.level}.", best.evidence_id
    return None  # don't declare someone ineligible from a missing line


def _describe(levels: set[str]) -> str:
    ordered = sorted(levels, key=lambda level: _LEVEL_RANK[level])
    return " or ".join(ordered)
