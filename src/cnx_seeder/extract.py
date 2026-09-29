"""Untrusted HTML and RSS parsing. Heuristics fail toward rejection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin
from xml.etree import ElementTree

from cnx_seeder.bounds import ARTICLE_PATH_RE, LISTING_PAGE_RE
from cnx_seeder.classify import DENYLIST
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
    chosen_url: str | None = None


# Share widgets, social, marketplaces, and infra. Evidence only: never primary_url or homepage.
PRIMARY_BLOCK = frozenset(
    {
        "addtoany.com",
        "addthis.com",
        "sharethis.com",
        "t.me",
        "telegram.me",
        "telegram.org",
        "x.com",
        "twitter.com",
        "facebook.com",
        "fb.com",
        "linkedin.com",
        "youtube.com",
        "youtu.be",
        "patreon.com",
        "amzn.to",
        "amazon.com",
        "amazon.co.uk",
        "aliexpress.com",
        "alibaba.com",
        "ebay.com",
        "banggood.com",
        "walmart.com",
        "github.com",
        "github.io",
        "gitlab.com",
        "gitlab.io",
        "hackster.io",
        "armbian.com",
        "instagram.com",
        "reddit.com",
        "pinterest.com",
        "tiktok.com",
        "medium.com",
        "wikipedia.org",
        "follow.it",
    }
)


class _Frame:
    def __init__(self, tag: str, *, skip: bool, in_entry: bool, drop_links: bool) -> None:
        self.tag = tag
        self.skip = skip
        self.in_entry = in_entry
        self.drop_links = drop_links
        self.text_buf: list[str] = []


class _PageParser(HTMLParser):
    """Collect visible text and links.

    When ``div.entry-content`` exists, links and body text come only from that
    subtree. The author box, AddToAny share kit, and the trailing Support CNX
    donate paragraph are not article content. Pages without that container
    (fixtures, OEM sites) keep every link.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._raw_skip = 0
        self._capture_title = False
        self.title_parts: list[str] = []
        self.all_text: list[str] = []
        self.body_text: list[str] = []
        self.all_links: list[Link] = []
        self.body_links: list[Link] = []
        self.saw_entry = False
        self._stack: list[_Frame] = []
        self._anchor: list[str] | None = None
        self._href = ""
        self._anchor_in_body = False

    def _classes(self, attrs: list[tuple[str, str | None]]) -> set[str]:
        for key, value in attrs:
            if key == "class" and value:
                return set(value.split())
        return set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._raw_skip += 1
            return
        if self._raw_skip:
            return
        classes = self._classes(attrs)
        parent = self._stack[-1] if self._stack else None
        parent_skip = parent.skip if parent else False
        parent_entry = parent.in_entry if parent else False
        is_entry = "entry-content" in classes
        if is_entry:
            self.saw_entry = True
        skip = parent_skip or bool(
            classes & {"saboxplugin-wrap", "addtoany_share_save_container", "a2a_kit"}
        )
        drop_links = parent.drop_links if parent else False
        frame = _Frame(tag, skip=skip, in_entry=parent_entry or is_entry, drop_links=drop_links)
        self._stack.append(frame)
        if tag == "title" and not skip:
            self._capture_title = True
        if tag == "a" and not skip:
            href = ""
            for key, value in attrs:
                if key == "href" and value:
                    href = value
            self._href = href
            self._anchor = []
            self._anchor_in_body = frame.in_entry and not frame.drop_links

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._raw_skip:
            self._raw_skip -= 1
            return
        if self._raw_skip:
            return
        if tag == "title":
            self._capture_title = False
        if tag == "a" and self._anchor is not None:
            frame = self._stack[-1] if self._stack else None
            drop = frame.drop_links if frame else False
            if not drop and self._href:
                link = Link(self._href, "".join(self._anchor).strip())
                self.all_links.append(link)
                if self._anchor_in_body:
                    self.body_links.append(link)
            self._anchor = None
            self._href = ""
            self._anchor_in_body = False
        while self._stack:
            frame = self._stack.pop()
            if frame.tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._raw_skip or not data:
            return
        frame = self._stack[-1] if self._stack else None
        skip = frame.skip if frame else False
        if skip:
            return
        if self._capture_title:
            self.title_parts.append(data)
        self.all_text.append(data)
        if frame and frame.in_entry and not frame.drop_links:
            self.body_text.append(data)
        paragraph = next((item for item in reversed(self._stack) if item.tag == "p"), None)
        if paragraph is not None and not paragraph.skip:
            paragraph.text_buf.append(data)
            blob = "".join(paragraph.text_buf).strip().casefold()
            if blob.startswith("support cnx software"):
                seen = False
                for item in self._stack:
                    if item is paragraph:
                        seen = True
                    if seen:
                        item.drop_links = True
        if self._anchor is not None and not (frame and frame.drop_links):
            self._anchor.append(data)

    def handle_comment(self, data: str) -> None:
        return None

    def chosen_text(self) -> list[str]:
        if self.saw_entry:
            return self.body_text
        return self.all_text

    def chosen_links(self) -> list[Link]:
        if self.saw_entry:
            return self.body_links
        return self.all_links


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
    if _truncated_markup(text):
        return ParsedPage("", "", [], (), malformed=True)
    parser = _PageParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        return ParsedPage("", "", [], (), malformed=True)
    visible = " ".join(part.strip() for part in parser.chosen_text() if part.strip())
    if not visible:
        return ParsedPage("", "", [], (), malformed=True)
    folded = visible.casefold()
    if any(phrase in folded for phrase in _INSTRUCTION):
        return ParsedPage(visible, visible, [], normalize_tokens(visible), instruction=True)
    title = " ".join(parser.title_parts).strip() or visible[:120]
    links: list[Link] = []
    for link in parser.chosen_links():
        if not link.href:
            continue
        absolute = urljoin(base_url, link.href)
        if absolute.startswith("http://") or absolute.startswith("https://"):
            links.append(Link(absolute, link.anchor))
    return ParsedPage(title, visible, links, normalize_tokens(visible))


def _truncated_markup(text: str) -> bool:
    """Visible-but-cut documents only.

    A page that opened ``html`` or ``body`` and closed neither is truncated,
    as is a document cut mid-tag. Unclosed ``p`` or ``li`` inside a page that
    still has ``</body>`` or ``</html>`` is ordinary WordPress markup.
    """
    folded = text.casefold()
    has_html = "</html>" in folded
    has_body = "</body>" in folded
    opened = "<html" in folded or "<body" in folded
    if opened and not has_html and not has_body:
        return True
    last = text.rfind("<")
    if last != -1 and ">" not in text[last:] and (not has_html or not has_body):
        return True
    return False


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
    """Brand tokens immediately before the first product token.

    A product token contains a digit, or is a product word such as ``zero``
    after at least one brand token. Leading words are not the brand when a
    function word separates them from that product (``Hands on with the Acme
    Board X2`` is ``acme``).
    """
    product_at = None
    seen_brand = False
    for index, tok in enumerate(tokens):
        if tok in _FUNCTION or tok in _PRODUCT_CLASS:
            continue
        if any(ch.isdigit() for ch in tok) or (seen_brand and tok in _PRODUCT_WORDS):
            product_at = index
            break
        seen_brand = True
    if product_at is None:
        kept = [tok for tok in tokens if tok not in _FUNCTION]
        return tuple(kept[:3]) if kept else None
    picked: list[str] = []
    index = product_at - 1
    while index >= 0 and len(picked) < 3:
        tok = tokens[index]
        if tok in _FUNCTION:
            break
        if tok not in _PRODUCT_CLASS:
            picked.append(tok)
        index -= 1
    return tuple(reversed(picked)) if picked else None


def _leading_alias(tokens: tuple[str, ...], names: tuple[tuple[str, ...], ...]) -> tuple[str, ...] | None:
    best: tuple[str, ...] | None = None
    for name in names:
        size = len(name)
        if size and tokens[:size] == name and (best is None or size > len(best)):
            best = name
    return best


def _domain_label(domain: str) -> str:
    return domain.split(".")[0].replace("-", "")


def _brand_matches(domain: str, subject: tuple[str, ...]) -> bool:
    if not subject:
        return False
    label = _domain_label(domain)
    for size in range(len(subject), 0, -1):
        joined = "".join(subject[:size])
        if len(joined) >= 3 and joined in label:
            return True
    return False


def _longest_brand_prefix(subject: tuple[str, ...], domain: str) -> tuple[str, ...] | None:
    label = _domain_label(domain)
    best: tuple[str, ...] | None = None
    for size in range(1, len(subject) + 1):
        prefix = subject[:size]
        joined = "".join(prefix)
        if len(joined) >= 3 and joined in label:
            best = prefix
    return best


def _product_anchor(anchor: str) -> bool:
    text = " ".join(anchor.casefold().split())
    return text in {"product page", "the product page"} or text.endswith(" product page")


def _blocked_primary(domain: str) -> bool:
    if domain in PRIMARY_BLOCK:
        return True
    head, _, tail = domain.partition(".")
    return head == "discord" and tail in {"com", "gg"}


def _choose_primary(
    subject: tuple[str, ...], links: list[Link]
) -> tuple[str | None, str | None, str | None]:
    """Return (domain, url, reason). url is None when the domain is denylist-only."""
    usable: list[tuple[Link, str]] = []
    denied: list[tuple[Link, str]] = []
    for link in links:
        domain = _eligible_domain(link.href)
        if domain is None:
            continue
        if _blocked_primary(domain):
            denied.append((link, domain))
            continue
        usable.append((link, domain))
    branded = [(link, domain) for link, domain in usable if _brand_matches(domain, subject)]
    pool = branded if branded else usable
    if not pool:
        for _link, domain in denied:
            if domain in DENYLIST:
                return domain, None, None
        return None, None, "primary_domain_unresolved" if subject else None
    if not branded:
        counts: dict[str, int] = {}
        first: dict[str, Link] = {}
        for link, domain in pool:
            counts[domain] = counts.get(domain, 0) + 1
            first.setdefault(domain, link)
        if len(counts) > 1:
            top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            if top[0][1] == top[1][1]:
                return None, None, "ambiguous_primary"
            domain = top[0][0]
            return domain, first[domain].href, None
    pool.sort(key=lambda item: (not _product_anchor(item[0].anchor),))
    link, domain = pool[0]
    return domain, link.href, None


def _eligible_domain(url: str) -> str | None:
    host = host_of(url)
    if host is None or is_cnx_host(host):
        return None
    domain = registrable_domain(host)
    return domain


def extract_subject(
    title: str,
    page: ParsedPage | None = None,
    *,
    alias_names: tuple[tuple[str, ...], ...] = (),
) -> Extraction:
    """Subject comes from the title brand, never from anchor text or chrome.

    A leading alias tuple is decided before any domain is chosen, so a known
    vendor still matches when the only links are social or share widgets.
    """
    raw_title = title.strip()
    title_tokens = normalize_tokens(raw_title)
    body_tokens = page.tokens if page is not None else ()
    masked_title, title_mentions = _mask(title_tokens)
    _, body_mentions = _mask(body_tokens[:200] if len(body_tokens) > 200 else body_tokens)
    mentions = title_mentions + [item for item in body_mentions if item not in title_mentions]
    subject = (
        _leading_alias(masked_title, alias_names)
        or _company_name(masked_title)
        or _brand_before_product(masked_title)
    )
    links = page.links if page is not None else []
    if subject is None:
        return Extraction(raw_title, "", "", (), mentions, None, links, "vendor_name_unresolved")
    domain, chosen, reason = _choose_primary(subject, links)
    if (
        subject
        and domain
        and reason is None
        and subject not in alias_names
    ):
        prefix = _longest_brand_prefix(subject, domain)
        if prefix:
            subject = prefix
    name = " ".join(subject)
    if reason == "ambiguous_primary":
        return Extraction(raw_title, name, name, subject, mentions, None, links, reason)
    if domain is None:
        return Extraction(
            raw_title,
            name,
            name,
            subject,
            mentions,
            None,
            links,
            reason or "primary_domain_unresolved",
        )
    return Extraction(raw_title, name, name, subject, mentions, domain, links, None, chosen)


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


_LISTING_RE = re.compile(r"\b([A-Z][A-Za-z0-9]+)\s+Board\b")


def other_manufacturer_evidence(
    pages: list[ParsedPage],
    subject: tuple[str, ...],
    own_domain: str,
    alias_names: tuple[tuple[str, ...], ...],
) -> str | None:
    """Evidence that this site sells other makers, or None.

    Capitalised product words are not evidence. A catalogue of two other
    ``{Name} Board`` listings, a whole-token roster/alias brand, or an outbound
    link to another manufacturer's registrable domain is.
    """
    listings: set[str] = set()
    brands: set[tuple[str, ...]] = set()
    domains: set[str] = set()
    for page in pages:
        for match in _LISTING_RE.findall(page.text):
            token = normalize_tokens(match)
            if not token or token == subject or (subject and token[0] == subject[0]):
                continue
            listings.add(token[0])
        for name in alias_names:
            if not name or name == subject:
                continue
            size = len(name)
            if any(page.tokens[i : i + size] == name for i in range(0, len(page.tokens) - size + 1)):
                brands.add(name)
        for link in page.links:
            host = host_of(link.href)
            if host is None or is_cnx_host(host):
                continue
            domain = registrable_domain(host)
            if domain == own_domain or domain in DENYLIST or _blocked_primary(domain):
                continue
            domains.add(domain)
    if len(listings) >= 2:
        return "catalogue"
    if brands:
        return "alias_brand"
    if domains:
        return "other_domain"
    return None
