"""Extract plain text from an uploaded resume PDF."""

import io
import logging

from pypdf import PdfReader
from pypdf.errors import PdfReadError

log = logging.getLogger(__name__)

MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 10


class PdfTextError(ValueError):
    """The PDF can't be turned into usable text. The message is safe to show the user."""


def pdf_to_text(data: bytes) -> str:
    if not data.startswith(b"%PDF"):
        raise PdfTextError("That file isn't a PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise PdfTextError("This PDF is password-protected. Export an unlocked copy, or paste the text instead.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise PdfTextError(f"Resumes over {MAX_PDF_PAGES} pages aren't supported.")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError as e:
        log.info("unreadable pdf: %s", e)
        raise PdfTextError("This PDF couldn't be read. Try re-exporting it, or paste the text instead.") from e

    if len(text.split()) < 20:
        raise PdfTextError(
            "No text found in this PDF — it may be a scanned image. Paste your resume text instead."
        )
    return text
