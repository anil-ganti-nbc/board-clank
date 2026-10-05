"""First-party domain checks. A CNX URL is not evidence until Board accepts the host."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?)+$")
_REFUSED_SUFFIXES = (".local", ".localhost", ".internal", ".invalid")
_REFUSED_HOSTS = frozenset({"localhost", "metadata.google.internal"})


def normalize_domain(value: str) -> str:
    text = value.strip().lower().rstrip(".")
    if text.startswith("www."):
        text = text[4:]
    return text


def domain_refusal(value: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return "missing_domain"
    text = normalize_domain(value)
    if text != value.strip().lower().rstrip(".") and not value.strip().lower().startswith("www."):
        return "invalid_domain"
    if any(ch in text for ch in "/?#@:\\ "):
        return "invalid_domain"
    try:
        ipaddress.ip_address(text)
        return "invalid_domain"
    except ValueError:
        pass
    if text in _REFUSED_HOSTS or text.endswith(_REFUSED_SUFFIXES) or _HOST.fullmatch(text) is None:
        return "invalid_domain"
    return None


def normalize_oem(name: str) -> str:
    text = name.strip().lower().replace("_", " ")
    text = "-".join(part for part in text.replace("-", " ").split() if part)
    return text


def url_host(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.hostname is None:
        return None
    return normalize_domain(parsed.hostname)


def url_on_domain(url: str, domain: str) -> bool:
    host = url_host(url)
    claimed = normalize_domain(domain)
    if host is None or domain_refusal(claimed):
        return False
    return host == claimed or host.endswith("." + claimed)


def same_site(left: str, right: str, domain: str) -> bool:
    return url_on_domain(left, domain) and url_on_domain(right, domain)
