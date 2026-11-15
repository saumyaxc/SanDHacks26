"""Check that an LLM-proposed URL is real before showing it to a user.

The URL comes from model output, and the model reads untrusted JD/resume text, so
treat it as attacker-controlled: only public https hosts, re-checked on every
redirect, so a prompt-injected URL can't make the server probe internal addresses.

Limits (accepted): a live page can still be the wrong page (soft 404s), and some
sites block bots (403) — those just fall back to a search link.
"""

import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlsplit

import httpx

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 4.0
_MAX_REDIRECTS = 3
_HEADERS = {"User-Agent": "resume-gap-link-check/1.0"}


def _is_public_https(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return False
    # Every address the name resolves to must be public (blocks localhost, 10.x, 169.254.x, ...).
    return bool(infos) and all(ipaddress.ip_address(info[4][0]).is_global for info in infos)


def url_is_live(url: str) -> bool:
    """True if `url` is a public https page that loads (status < 400) within a few redirects."""
    try:
        with httpx.Client(timeout=_TIMEOUT_SECONDS, headers=_HEADERS, follow_redirects=False) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                if not _is_public_https(url):
                    return False
                # Stream so we only read headers, never a large body.
                with client.stream("GET", url) as response:
                    if response.is_redirect and (location := response.headers.get("location")):
                        url = urljoin(url, location)
                        continue
                    return response.status_code < 400
    except httpx.HTTPError as e:
        log.info("link check failed for %s: %s", url, e)
    return False
