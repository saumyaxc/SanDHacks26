from app.domain.redact import redact_resume
from app.domain.reflow import needs_reflow, reflow


def _one_word_per_line(lines: list[str]) -> str:
    """Mimic the broken copy-paste: words separated by ' ' lines, real lines by longer gaps."""
    out = []
    for line in lines:
        words = line.split()
        for i, w in enumerate(words):
            out.append(w)
            out.append(" " if i < len(words) - 1 else "        ")
        out.append("   ")
    return "\n".join(out)


LINES = [
    "EXPERIENCE",
    "Software Engineer Intern, Acme",
    "Jun 2025 - Aug 2025",
    "● Built a data pipeline in Python and Airflow processing 2,000 events per second",
    "● Cut query latency by 40% with Redis caching across three services",
    "TECHNICAL SKILLS",
    "Languages: Python, Java, C++, Go",
    "Frameworks: React, FastAPI, Kafka, Docker, Kubernetes, PostgreSQL, Redis, Airflow",
]


def test_rebuilds_lines_bullets_and_headings():
    broken = _one_word_per_line(LINES)
    assert needs_reflow(broken)
    assert reflow(broken).splitlines() == LINES


def test_attaches_punctuation_with_no_gap():
    words = ["Python"] + [" "] + ["and"] + [" "] + ["Java"] + [","] + [" "] + ["C++"] + ["  "] * 2
    text = "\n".join(words * 15)
    assert "Java, C++" in reflow(text)


def test_normal_resume_is_untouched():
    normal = "\n".join(LINES * 6)
    assert not needs_reflow(normal)
    assert reflow(normal) == normal


def test_redaction_runs_on_reflowed_text():
    broken = _one_word_per_line(["Alex Rivera", "alex@x.io | 555-123-4567", *LINES])
    text = redact_resume(broken).text
    assert "Alex" not in text and "alex@x.io" not in text
    assert "Languages: Python, Java, C++, Go" in text.splitlines()
