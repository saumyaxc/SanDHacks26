from datetime import date

import pytest

from app.domain.education import education_timeline, format_timeline
from app.domain.schemas import EvidenceItem

TODAY = date(2026, 11, 14)


def _edu(*lines: str) -> list[EvidenceItem]:
    return [EvidenceItem(id=f"ev-{i}", section="education", line=line, skills=[]) for i, line in enumerate(lines, 1)]


def test_current_masters_and_completed_bachelors():
    programs = education_timeline(
        _edu(
            "Master of Science, Computer Science\tSept. 2026 – Jun. 2028",
            "Bachelor of Science, Computer Science, Minor in Business\tSept. 2022 – Jun. 2026",
        ),
        TODAY,
    )
    assert format_timeline(programs) == (
        "ev-1 | master's | Sep 2026 – Jun 2028 | in progress (current program)\n"
        "ev-2 | bachelor's | Sep 2022 – Jun 2026 | completed"
    )


@pytest.mark.parametrize(
    ("line", "level", "status", "end"),
    [
        ("B.S. Data Science, expected May 2027", "bachelor's", "in progress", (2027, 5)),
        ("BA Economics 2019", "bachelor's", "completed", (2019, 6)),
        ("PhD, Physics, Aug 2024 – Present", "doctorate", "in progress", None),
        ("M.Eng. Robotics, 2021 - 2023", "master's", "completed", (2023, 6)),
        ("MS in Statistics (Fall 2027)", "master's", "in progress", (2027, 12)),
        ("Bachelor's in Nursing", "bachelor's", "unknown", None),
    ],
)
def test_parses_level_and_dates(line, level, status, end):
    (p,) = education_timeline(_edu(line), TODAY)
    assert (p.level, p.status, p.end) == (level, status, end)


def test_pairs_school_line_dates_with_degree_line():
    programs = education_timeline(
        _edu("University of Somewhere\tSep 2023 – May 2027", "Bachelor of Arts, History"),
        TODAY,
    )
    assert format_timeline(programs) == "ev-2 | bachelor's | Sep 2023 – May 2027 | in progress (current program)"


def test_ignores_coursework_and_non_education_lines():
    items = _edu("Coursework: Data Structures and Algorithms, Operating Systems")
    items.append(EvidenceItem(id="ev-9", section="experience", line="Software Intern, May 2025 – Aug 2025", skills=[]))
    assert education_timeline(items, TODAY) == []


from app.domain.education import judge_degree_rule  # noqa: E402

MS_STUDENT = education_timeline(
    _edu(
        "Master of Science, Computer Science\tSept. 2026 – Jun. 2028",
        "Bachelor of Science, Computer Science\tSept. 2022 – Jun. 2026",
    ),
    TODAY,
)


@pytest.mark.parametrize(
    ("rule", "status"),
    [
        ("A rising senior pursuing a BS computer science or related field", "not_met"),
        ("Must be an undergraduate student", "not_met"),
        ("Currently pursuing a Bachelor's or Master's degree", "met"),
        ("Currently enrolled in a Master's or PhD program", "met"),
        ("PhD candidates only", "not_met"),
        ("Bachelor's degree in Computer Science required", "met"),  # a qualification: MS exceeds it
        ("BS or higher in a technical field", "met"),
        ("Bachelor's or advanced degree", "met"),
    ],
)
def test_degree_rules_for_a_current_ms_student(rule, status):
    assert judge_degree_rule(rule, MS_STUDENT)[0] == status


def test_degree_rule_undecidable_without_levels_or_current_program():
    assert judge_degree_rule("Strong academic record", MS_STUDENT) is None
    graduated = education_timeline(_edu("B.S. Biology, 2019"), TODAY)
    assert judge_degree_rule("Currently pursuing a Bachelor's", graduated) is None
