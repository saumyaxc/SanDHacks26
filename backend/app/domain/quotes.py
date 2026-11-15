"""Verbatim-quote checks. Every line the product quotes must really exist in the source text.

Comparison ignores formatting noise that PDFs and LLMs introduce: bullet characters,
dashes, line wrapping, smart quotes, and case. It does NOT ignore word changes.
"""

import re

_QUOTE_CHARS = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})
_NOISE = re.compile(r"[\s•·▪●◦*\-–—]+")


def normalize_for_quote(text: str) -> str:
    return _NOISE.sub(" ", text.translate(_QUOTE_CHARS)).strip().lower()


def quote_in_text(quote: str, text: str) -> bool:
    q = normalize_for_quote(quote)
    return bool(q) and q in normalize_for_quote(text)
