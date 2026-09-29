"""Name normalization, registrable domains, and CNX host checks."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlsplit

from cnx_seeder.bounds import ALIAS_TABLE_VERSION

_LEGAL = frozenset({"inc", "llc", "ltd", "co", "corp", "gmbh", "limited", "corporation"})
_MULTI = {("co", "uk"), ("org", "uk"), ("ac", "uk"), ("com", "cn"), ("com", "au"), ("co", "jp")}
_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)


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


def registrable_domain(host: str) -> str:
    value = strip_host(host)
    labels = [part for part in value.split(".") if part]
    if len(labels) >= 3 and tuple(labels[-2:]) in _MULTI:
        return ".".join(labels[-3:])
    if len(labels) >= 2:
        return ".".join(labels[-2:])
    return value


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
