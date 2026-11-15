"""Rebuild real lines from resume text that arrived one word per line.

Text copied out of some PDFs (often LaTeX-built ones) puts every word on its own line, with
whitespace-only lines between them. The model then can't tell where a bullet or a skills
line starts, so whole skills go missing. The layout survives in the gaps:

    word, single " " line, word        -> same line (a space)
    word, no gap, ","                  -> same line, no space (punctuation)
    word, several / long blank lines   -> a line break
    "●" / "•" / "▪"                     -> starts a new line (a bullet)
    ALL-CAPS section heading            -> its own line ("TECHNICAL SKILLS", "EXPERIENCE")

Runs only when the text is clearly in that shape, so normal resumes pass through untouched.
"""

import re

# Not "–" or "*": dashes also separate dates ("2023 – 2025").
_BULLETS = {"●", "•", "▪", "◦", "■", "‣", "⁃"}
_HEADING_WORDS = {
    "summary", "profile", "objective", "about", "education", "experience", "work", "professional",
    "employment", "projects", "project", "skills", "technical", "certifications", "awards", "honors",
    "publications", "leadership", "activities", "coursework", "relevant", "research", "involvement",
}  # fmt: skip
_ATTACH_LEFT = re.compile(r"^[,.;:!?)\]%]")  # punctuation that belongs to the previous word
_MIN_WORDS = 40  # a short snippet isn't enough evidence of the broken layout
_ONE_WORD_SHARE = 0.85  # this share of non-empty lines being single words means "broken"


def needs_reflow(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < _MIN_WORDS:
        return False
    single = sum(1 for line in lines if len(line.split()) == 1)
    return single / len(lines) >= _ONE_WORD_SHARE


def reflow(text: str) -> str:
    """One word per line -> real lines. Returns `text` unchanged unless it needs it."""
    if not needs_reflow(text):
        return text

    out_lines: list[str] = []
    current = ""
    in_heading = False
    gap: list[str] = []  # whitespace-only lines since the previous word
    for line in text.splitlines():
        if not line.strip():
            gap.append(line)
            continue
        token = line.strip()
        heading = _is_heading_word(token)
        if not current:
            current = token
        elif token in _BULLETS or _is_break(gap) or (heading and not in_heading) or (in_heading and not heading):
            out_lines.append(current)  # a heading gets a line of its own, before and after
            current = token
        elif not gap and _ATTACH_LEFT.match(token):
            current += token
        else:
            current += " " + token
        in_heading = heading
        gap = []
    if current:
        out_lines.append(current)
    return "\n".join(out_lines)


def _is_heading_word(token: str) -> bool:
    word = token.strip(":")
    return word.isupper() and word.lower() in _HEADING_WORDS


def _is_break(gap: list[str]) -> bool:
    """A single one-space line is a word gap; anything bigger is a layout break."""
    return len(gap) >= 2 or any(len(g) > 1 for g in gap)
