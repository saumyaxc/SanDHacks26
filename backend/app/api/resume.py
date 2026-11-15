from fastapi import APIRouter, HTTPException, UploadFile

from app.domain.redact import redact_resume
from app.domain.schemas import MAX_INPUT_CHARS, ParsedResume
from app.services.pdf_text import MAX_PDF_BYTES, PdfTextError, pdf_to_text

router = APIRouter()


# Sync: PDF parsing is CPU-bound, so FastAPI runs it in a worker thread.
@router.post("/resume/pdf", response_model=ParsedResume)
def parse_resume_pdf(file: UploadFile) -> ParsedResume:
    """PDF -> plain text with contact details removed. Nothing is stored."""
    data = file.file.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, f"PDF is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB.")
    try:
        text = pdf_to_text(data)
    except PdfTextError as e:
        raise HTTPException(422, str(e))

    redaction = redact_resume(text)
    if len(redaction.text) > MAX_INPUT_CHARS:
        raise HTTPException(422, f"This resume has over {MAX_INPUT_CHARS:,} characters of text; that's too long.")
    return ParsedResume(text=redaction.text, removed=redaction.removed)
