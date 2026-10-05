"""Bounded first-party fetch for research qualification. It never writes Board state."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from board_clank.research.domain import same_site, url_on_domain


class FetchRejected(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class FetchEvidence:
    requested_url: str
    final_url: str
    status: int
    body_sha256: str
    byte_length: int
    body_text: str

    def as_dict(self) -> dict[str, object]:
        return {
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "status": self.status,
            "body_sha256": self.body_sha256,
            "byte_length": self.byte_length,
        }


class _SameSiteRedirect(HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def __init__(self, domain: str) -> None:
        super().__init__()
        self.domain = domain

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if not url_on_domain(newurl, self.domain):
            raise FetchRejected("redirect_domain_mismatch")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_first_party(url: str, claimed_domain: str, *, timeout: float = 15.0) -> FetchEvidence:
    if not url_on_domain(url, claimed_domain):
        raise FetchRejected("third_party_only")
    # Leave User-Agent unset so urllib sends its normal Python-urllib token.
    # A custom product token is answered 404 by some CDNs while that default is not.
    request = Request(url, method="GET")
    try:
        with build_opener(_SameSiteRedirect(claimed_domain)).open(request, timeout=timeout) as response:
            final = response.geturl()
            if not same_site(url, final, claimed_domain):
                raise FetchRejected("redirect_domain_mismatch")
            body = response.read(1_000_001)
            if len(body) > 1_000_000:
                raise FetchRejected("body_too_large")
            status = int(getattr(response, "status", 0) or response.getcode() or 0)
    except FetchRejected:
        raise
    except HTTPError as exc:
        raise FetchRejected(f"http_error:{exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise FetchRejected("fetch_failed") from exc
    if status != 200:
        raise FetchRejected(f"http_error:{status}")
    return FetchEvidence(
        requested_url=url,
        final_url=final,
        status=status,
        body_sha256="sha256:" + hashlib.sha256(body).hexdigest(),
        byte_length=len(body),
        body_text=body.decode("utf-8", errors="replace"),
    )
