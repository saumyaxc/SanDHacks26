from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _pdf(lines: list[str]) -> bytes:
    """A minimal valid one-page PDF with real (extractable) text lines."""

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    ops = ["BT", "/F1 11 Tf", "14 TL", "50 750 Td"] + [f"({esc(line)}) Tj T*" for line in lines] + ["ET"]
    stream = "\n".join(ops).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


RESUME_LINES = [
    "Jane Doe",
    "jane.doe@gmail.com | (858) 555-1234 | linkedin.com/in/janedoe",
    "EXPERIENCE",
    "Software Intern, Acme - San Diego, CA",
    "Built REST APIs in Python and FastAPI serving ten thousand daily users across three regions",
    "Deployed services to Google Cloud Run with Docker and wrote the CI pipeline in GitHub Actions",
    "SKILLS",
    "Python, SQL, Docker, React, TypeScript",
]


def _upload(data: bytes, name: str = "resume.pdf"):
    return client.post("/api/resume/pdf", files={"file": (name, data, "application/pdf")})


def test_pdf_upload_returns_text_without_contact_info():
    r = _upload(_pdf(RESUME_LINES))
    assert r.status_code == 200
    body = r.json()
    for secret in ("Jane", "gmail", "555", "linkedin"):
        assert secret not in body["text"]
    assert "Built REST APIs in Python" in body["text"]
    assert "Software Intern, Acme - San Diego, CA" in body["text"]  # body location kept
    assert sorted(body["removed"]) == ["email", "link", "name", "phone"]


def test_rejects_non_pdf():
    r = _upload(b"hello, I am a text file", name="resume.pdf")
    assert r.status_code == 422 and "isn't a PDF" in r.json()["detail"]


def test_rejects_pdf_without_text():
    r = _upload(_pdf([]))
    assert r.status_code == 422 and "scanned" in r.json()["detail"]


def test_rejects_oversized_upload():
    r = _upload(b"%PDF" + b"0" * (5 * 1024 * 1024 + 10))
    assert r.status_code == 413
