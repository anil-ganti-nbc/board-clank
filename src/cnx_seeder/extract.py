"""Untrusted HTML and RSS parsing. Heuristics fail toward rejection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin
from xml.etree import ElementTree

from cnx_seeder.bounds import ARTICLE_PATH_RE, LISTING_PAGE_RE
from cnx_seeder.normalize import host_of, is_cnx_host, normalize_tokens, registrable_domain

_INSTRUCTION = (
    "ignore previous instructions",
    "ignore all previous",
    "system prompt",
    "you are chatgpt",
    "disregard the above",
    "admit this source",
    "promotion_freeze",
    "enabled: true",
)
_LEGAL = frozenset({"inc", "llc", "ltd", "co", "corp", "gmbh", "limited", "corporation"})
_PRODUCT_CLASS = frozenset({"sbc", "board", "boards", "carrier", "module", "som", "devkit", "kit"})
_FUNCTION = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "of",
        "to",
        "for",
        "and",
        "or",
        "with",
        "on",
        "by",
        "from",
        "in",
        "at",
        "as",
        "it",
        "its",
        "this",
        "that",
        "into",
        "over",
        "per",
        "via",
    }
)
_PRODUCT_WORDS = frozenset({"pro", "plus", "max", "ultra", "zero", "mini", "lite"})
_TWO_CUES = (
    ("alternative", "to"),
    ("compared", "to"),
    ("comparison", "with"),
    ("similar", "to"),
    ("powered", "by"),
    ("based", "on"),
)
_ARTICLE_RE = re.compile(ARTICLE_PATH_RE)
_PAGE_RE = re.compile(LISTING_PAGE_RE)
_SURFACE_BITS = (
    "about",
    "company",
    "about-us",
    "product",
    "products",
    "board",
    "boards",
    "sbc",
    "devices",
    "datasheet",
    "specs",
    "specifications",
)
_SURFACE_ONLY = (
    "product",
    "products",
    "board",
    "boards",
    "sbc",
    "devices",
    "datasheet",
    "specs",
    "specifications",
)


@dataclass
class Link:
    href: str
    anchor: str


@dataclass
class ParsedPage:
    title: str
    text: str
    links: list[Link]
    tokens: tuple[str, ...]
    malformed: bool = False
    instruction: bool = False


@dataclass
class Extraction:
    article_title: str
    discovered_name: str
    normalized_name: str
    subject: tuple[str, ...]
    mentions: list[str] = field(default_factory=list)
    domain: str | None = None
    links: list[Link] = field(default_factory=list)
    reason: str | None = None


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._capture_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[Link] = []
        self._anchor: list[str] | None = None
        self._href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "title":
            self._capture_title = True
        if tag == "a":
            href = ""
            for key, value in attrs:
                if key == "href" and value:
                    href = value
            self._href = href
            self._anchor = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
            return
        if self._skip:
            return
        if tag == "title":
            self._capture_title = False
        if tag == "a" and self._anchor is not None:
            self.links.append(Link(self._href, "".join(self._anchor).strip()))
            self._anchor = None
            self._href = ""

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._capture_title:
            self.title_parts.append(data)
        self.text_parts.append(data)
        if self._anchor is not None:
            self._anchor.append(data)

    def handle_comment(self, data: str) -> None:
        return None


def parse_html(raw: bytes, *, base_url: str, content_type: str = "") -> ParsedPage:
    """Parse untrusted HTML tolerantly.

    Real article pages are not well-formed XML. ``>`` in text and attributes,
    void tags, unclosed ``p``/``li``, and inline scripts are normal. Malformed
    means the page cannot be used: empty, a non-HTML content type, a decode
    that leaves no markup, or no visible text after script/style/comments are
    dropped.
    """
    if not raw or not raw.strip():
        return ParsedPage("", "", [], (), malformed=True)
    ctype = content_type.casefold()
    if ctype and "html" not in ctype and "xml" not in ctype:
        return ParsedPage("", "", [], (), malformed=True)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", "replace")
        if "<" not in text:
            return ParsedPage("", "", [], (), malformed=True)
    parser = _PageParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        return ParsedPage("", "", [], (), malformed=True)
    visible = " ".join(part.strip() for part in parser.text_parts if part.strip())
    if not visible:
        return ParsedPage("", "", [], (), malformed=True)
    folded = visible.casefold()
    if any(phrase in folded for phrase in _INSTRUCTION):
        return ParsedPage(visible, visible, [], normalize_tokens(visible), instruction=True)
    title = " ".join(parser.title_parts).strip() or visible[:120]
    links: list[Link] = []
    for link in parser.links:
        if not link.href:
            continue
        absolute = urljoin(base_url, link.href)
        if absolute.startswith("http://") or absolute.startswith("https://"):
            links.append(Link(absolute, link.anchor))
    return ParsedPage(title, visible, links, normalize_tokens(visible))


def _mask(tokens: tuple[str, ...]) -> tuple[tuple[str, ...], list[str]]:
    masked = [False] * len(tokens)
    mentions: list[str] = []

    def take_name(start: int, end: int) -> None:
        chunk = [tokens[i] for i in range(start, end) if not masked[i] and tokens[i] not in _FUNCTION]
        if not chunk:
            return
        mentions.append(" ".join(chunk))
        for i in range(start, end):
            masked[i] = True

    i = 0
    while i < len(tokens):
        pair = (tokens[i], tokens[i + 1]) if i + 1 < len(tokens) else None
        if pair in _TWO_CUES or tokens[i] in {"vs", "versus", "like", "uses"}:
            masked[i] = True
            if pair in _TWO_CUES:
                masked[i + 1] = True
            begin = i + (2 if pair in _TWO_CUES else 1)
            end = begin
            while end < len(tokens) and end < begin + 4 and tokens[end] not in _FUNCTION | {"alternative", "compatible"}:
                end += 1
                if tokens[end - 1] and any(ch.isdigit() for ch in tokens[end - 1]):
                    break
            if end > begin:
                take_name(begin, end)
            i = max(end, i + 1)
            continue
        if tokens[i] in {"alternative", "compatible"} and i > 0:
            begin = i - 1
            while begin >= 0 and i - begin <= 4 and tokens[begin] not in _FUNCTION:
                begin -= 1
            begin += 1
            if begin < i:
                take_name(begin, i)
            masked[i] = True
        i += 1
    kept = tuple(tok for tok, flag in zip(tokens, masked) if not flag)
    return kept, mentions


def _company_name(tokens: tuple[str, ...]) -> tuple[str, ...] | None:
    for index, token in enumerate(tokens):
        if token not in _LEGAL or index == 0:
            continue
        begin = index - 1
        picked: list[str] = []
        while begin >= 0 and len(picked) < 4 and tokens[begin] not in _FUNCTION:
            picked.append(tokens[begin])
            begin -= 1
        if picked:
            return tuple(reversed(picked))
    return None


def _brand_before_product(tokens: tuple[str, ...]) -> tuple[str, ...] | None:
    digit_at = next((i for i, tok in enumerate(tokens) if any(ch.isdigit() for ch in tok)), None)
    if digit_at is None:
        kept = [tok for tok in tokens if tok not in _FUNCTION]
        return tuple(kept[:3]) if kept else None
    picked: list[str] = []
    index = digit_at - 1
    while index >= 0 and len(picked) < 3:
        tok = tokens[index]
        if tok in _FUNCTION:
            break
        if tok not in _PRODUCT_CLASS:
            picked.append(tok)
        index -= 1
    if picked:
        return tuple(reversed(picked))
    if len(tokens) == 1:
        return tokens
    return None


def _eligible_domain(url: str) -> str | None:
    host = host_of(url)
    if host is None or is_cnx_host(host):
        return None
    domain = registrable_domain(host)
    return domain


def extract_subject(title: str, page: ParsedPage | None = None) -> Extraction:
    raw_title = title.strip()
    title_tokens = normalize_tokens(raw_title)
    body_tokens = page.tokens if page is not None else ()
    masked_title, title_mentions = _mask(title_tokens)
    _, body_mentions = _mask(body_tokens[:200] if len(body_tokens) > 200 else body_tokens)
    mentions = title_mentions + [item for item in body_mentions if item not in title_mentions]
    subject = _company_name(masked_title) or _brand_before_product(masked_title)
    links = page.links if page is not None else []
    domain: str | None = None
    if subject is None:
        for link in links:
            anchor_tokens = normalize_tokens(link.anchor)
            kept, _ = _mask(anchor_tokens)
            brand = _company_name(kept) or _brand_before_product(kept)
            dom = _eligible_domain(link.href)
            if brand and dom:
                subject = brand
                domain = dom
                break
    if subject is None:
        return Extraction(raw_title, "", "", (), mentions, None, links, "vendor_name_unresolved")
    if domain is None:
        counts: dict[str, int] = {}
        for link in links:
            dom = _eligible_domain(link.href)
            if dom:
                counts[dom] = counts.get(dom, 0) + 1
        if len(counts) == 1:
            domain = next(iter(counts))
        elif len(counts) > 1:
            top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            if top[0][1] == top[1][1]:
                return Extraction(
                    raw_title,
                    " ".join(subject),
                    " ".join(subject),
                    subject,
                    mentions,
                    None,
                    links,
                    "ambiguous_primary",
                )
            domain = top[0][0]
        else:
            return Extraction(
                raw_title,
                " ".join(subject),
                " ".join(subject),
                subject,
                mentions,
                None,
                links,
                "primary_domain_unresolved",
            )
    name = " ".join(subject)
    return Extraction(raw_title, name, name, subject, mentions, domain, links, None)


def feed_is_malformed(raw: bytes) -> bool:
    text = raw.decode("utf-8", "replace").casefold()
    if "<!doctype" in text or "<!entity" in text:
        return True
    try:
        ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return True
    return False


def parse_feed_items(raw: bytes) -> list[tuple[str, str, str | None]]:
    """Return (url, title, pubdate) in document order."""
    root = ElementTree.fromstring(raw)
    items: list[tuple[str, str, str | None]] = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in {"item", "entry"}:
            continue
        title = ""
        link = ""
        published = None
        description = ""
        for child in list(node):
            ctag = child.tag.rsplit("}", 1)[-1]
            if ctag == "title" and child.text:
                title = child.text.strip()
            elif ctag == "link":
                href = child.attrib.get("href") or (child.text or "")
                if href and not link:
                    link = href.strip()
            elif ctag in {"pubDate", "published", "updated"} and child.text:
                published = child.text.strip()
            elif ctag in {"description", "summary"} and child.text:
                description = child.text
        folded = f"{title}\n{description}".casefold()
        if any(phrase in folded for phrase in _INSTRUCTION):
            continue
        host = host_of(link)
        if host is None or not is_cnx_host(host):
            continue
        from urllib.parse import urlsplit

        path = urlsplit(link).path or ""
        if not _ARTICLE_RE.match(path):
            continue
        items.append((link, title, published))
    return items


def listing_links(page: ParsedPage) -> tuple[list[str], list[str]]:
    articles: list[str] = []
    pages: list[str] = []
    for link in page.links:
        host = host_of(link.href)
        if host is None or not is_cnx_host(host):
            continue
        from urllib.parse import urlsplit

        path = urlsplit(link.href).path or ""
        if _ARTICLE_RE.match(path):
            articles.append(link.href)
        elif _PAGE_RE.match(path):
            pages.append(link.href)
    return articles, pages


def path_has(url: str, bits: tuple[str, ...]) -> bool:
    from urllib.parse import urlsplit

    path = (urlsplit(url).path or "").casefold()
    return any(bit in path for bit in bits)


def is_surface_path(url: str) -> bool:
    return path_has(url, _SURFACE_ONLY)


def is_about_path(url: str) -> bool:
    return path_has(url, ("about", "company", "about-us"))


def page_has_tokens(page: ParsedPage, subject: tuple[str, ...]) -> bool:
    if not subject:
        return False
    hay = page.tokens
    size = len(subject)
    return any(hay[i : i + size] == subject for i in range(0, len(hay) - size + 1))


_SCOPE = (
    "single-board computer",
    "single board computer",
    "development board",
    "dev board",
    "system on module",
    "compute module",
    "specifications",
    "datasheet",
    "sbc",
)
_IDENTITY = ("we design", "designed by", "we manufacture", "manufacturer", "our boards", "about us")
_CART = ("add to cart", "buy now", "add to basket")


def has_scope(text: str) -> bool:
    folded = text.casefold()
    return any(term in folded for term in _SCOPE)


def has_identity(text: str) -> bool:
    folded = text.casefold()
    return any(term in folded for term in _IDENTITY)


def has_cart(text: str) -> bool:
    folded = text.casefold()
    return any(term in folded for term in _CART)


_BRAND_RE = re.compile(r"\b([A-Z][A-Za-z0-9]+)\b")
_BRAND_SKIP = _PRODUCT_CLASS | _FUNCTION | {"sbc", "html", "http", "https"}


def foreign_brands(text: str, subject: tuple[str, ...]) -> set[str]:
    found: set[str] = set()
    subject_join = " ".join(subject)
    for match in _BRAND_RE.findall(text):
        token = normalize_tokens(match)
        if not token or token[0] in _BRAND_SKIP:
            continue
        if token == subject or token[0] == subject_join:
            continue
        if subject and token[0] == subject[0]:
            continue
        found.add(token[0])
    return found
