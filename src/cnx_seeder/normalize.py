"""Name normalization, registrable domains, and CNX host checks."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from cnx_seeder.bounds import ALIAS_TABLE_VERSION

_LEGAL = frozenset({"inc", "llc", "ltd", "co", "corp", "gmbh", "limited", "corporation"})
_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
_TRACKING = re.compile(r"^(?:utm_.+|token|key|sig)$", re.IGNORECASE)
# Mozilla Public Suffix List, VERSION 2026-09-24_13-26-36_UTC,
# commit a179a48c465e818cfd8d626691cb317985da87fb. Loaded from disk only.
_PSL_PATH = Path(__file__).resolve().parent / "data" / "public_suffix_list.dat"
PSL_SHA256 = "257b298daca42f6d8ec964e238c2a55518e14f09d3117917ec8acee6f188503e"


def normalize_tokens(text: str) -> tuple[str, ...]:
    value = unicodedata.normalize("NFKC", text).casefold()
    value = value.replace("&", " and ")
    value = _PUNCT.sub(" ", value)
    tokens = [tok for tok in value.split() if tok]
    if tokens and tokens[-1] in _LEGAL:
        tokens = tokens[:-1]
    return tuple(tokens)


def strip_host(host: str) -> str:
    value = host.strip().rstrip(".").lower()
    if value.startswith("www."):
        value = value[4:]
    return value


def is_cnx_host(host: str) -> bool:
    value = strip_host(host)
    return value == "cnx-software.com" or value.endswith(".cnx-software.com")


class _PublicSuffixes:
    """eTLD+1 from the vendored list, including the private section."""

    def __init__(self, text: str) -> None:
        self.exact: set[str] = set()
        self.wild: set[str] = set()
        self.exception: set[str] = set()
        for raw in text.splitlines():
            line = raw.split("//", 1)[0].strip().lower().lstrip(".")
            if not line or line == "*":
                continue
            if line.startswith("!"):
                self._add(self.exception, line[1:])
            elif line.startswith("*."):
                self._add(self.wild, line[2:])
            else:
                self._add(self.exact, line)

    @staticmethod
    def _add(bucket: set[str], rule: str) -> None:
        if not rule:
            return
        bucket.add(rule)
        try:
            bucket.add(rule.encode("idna").decode("ascii"))
        except UnicodeError:
            return None

    def registrable(self, host: str) -> str:
        labels = [part for part in host.split(".") if part]
        if len(labels) < 2:
            return host
        best_len = 1
        best_pri = 0
        best = labels[-1:]
        for index in range(len(labels)):
            rest = labels[index:]
            candidate = ".".join(rest)
            if candidate in self.exception:
                score = (len(rest), 2)
                if score > (best_len, best_pri):
                    best_len, best_pri, best = len(rest), 2, rest[1:] or rest
            if candidate in self.exact:
                score = (len(rest), 1)
                if score > (best_len, best_pri):
                    best_len, best_pri, best = len(rest), 1, rest
            if len(rest) >= 2 and ".".join(rest[1:]) in self.wild:
                score = (len(rest), 1)
                if score > (best_len, best_pri):
                    best_len, best_pri, best = len(rest), 1, rest
        if len(best) >= len(labels):
            return host
        return ".".join(labels[-(len(best) + 1) :])


def _psl_bytes() -> bytes:
    crlf, cr, lf = bytes([13, 10]), bytes([13]), bytes([10])
    return _PSL_PATH.read_bytes().replace(crlf, lf).replace(cr, lf)


def _load_suffixes() -> _PublicSuffixes:
    raw = _psl_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PSL_SHA256:
        raise RuntimeError("public suffix list digest mismatch")
    return _PublicSuffixes(raw.decode("utf-8"))


_SUFFIXES = _load_suffixes()


def registrable_domain(host: str) -> str:
    value = strip_host(host)
    if not value:
        return value
    return _SUFFIXES.registrable(value)


def public_url(url: str) -> str:
    """Drop tracking and secret-looking query keys. The path is unchanged."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(key, val) for key, val in pairs if _TRACKING.match(key) is None]
    if len(kept) == len(pairs):
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def host_of(url: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    return strip_host(parts.hostname)


def candidate_key(normalized_name: str, domain: str) -> str:
    raw = f"{ALIAS_TABLE_VERSION}\n{normalized_name}\n{domain}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def lead_key(article_url: str, normalized_name: str) -> str:
    raw = f"{ALIAS_TABLE_VERSION}\n{article_url}\n{normalized_name}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
