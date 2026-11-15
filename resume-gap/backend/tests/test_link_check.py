import pytest

from app.services.link_check import _is_public_https, url_is_live


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.docker.com/",  # not https
        "ftp://example.com/file",
        "https://localhost/admin",
        "https://127.0.0.1/",
        "https://10.0.0.5/internal",
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
        "https://[::1]/",
        "https://no-such-host.invalid/",
        "not a url",
    ],
)
def test_rejects_non_public_or_non_https_urls(url):
    assert not _is_public_https(url)
    assert not url_is_live(url)  # rejected before any request is sent
