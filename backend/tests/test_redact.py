from app.domain.redact import describe_removed, redact_resume

RESUME = """Jane Q. Doe
San Diego, CA
jane.doe@gmail.com | (858) 555-1234 | linkedin.com/in/janedoe | github.com/janedoe

EDUCATION
University of California San Diego — MS Computer Science, 2025–2027

EXPERIENCE
Software Intern, Acme — San Diego, CA (2024–2025)
• Built REST APIs in Python serving 10,000 daily users
• Open-sourced the parser (https://github.com/janedoe/parser) used by 3 teams
• Cut latency 40% across 2019-2023 legacy endpoints
"""


def test_removes_header_contact_info():
    r = redact_resume(RESUME)
    for secret in ("Jane", "Doe", "gmail", "555", "linkedin", "janedoe"):
        assert secret not in r.text
    assert describe_removed(r.removed) == "name, email, phone, location, 3 links"


def test_keeps_body_content_including_locations_and_numbers():
    text = redact_resume(RESUME).text
    assert text.startswith("EDUCATION")
    assert "Software Intern, Acme — San Diego, CA (2024–2025)" in text  # body location kept
    assert "University of California San Diego" in text
    assert "10,000 daily users" in text and "2019-2023" in text  # not mistaken for phones
    assert "• Open-sourced the parser used by 3 teams" in text  # link removed, sentence kept


def test_without_headings_only_contact_details_are_removed():
    # No heading means no reliable header: never guess at names or locations.
    text = "Portland, OR\nBuilt dashboards for 3 teams\nEmail me: a@b.co"
    r = redact_resume(text)
    assert r.text == "Portland, OR\nBuilt dashboards for 3 teams\nEmail me"
    assert r.removed == ["email"]


def test_already_clean_resume_is_unchanged():
    clean = "SKILLS\nPython, SQL\n\nEXPERIENCE\nBuilt things in Python"
    r = redact_resume(clean)
    assert r.text == clean and r.removed == []


def test_fixes_pdf_ligatures():
    assert redact_resume("SKILLS\nWorkﬂow automation").text == "SKILLS\nWorkflow automation"
