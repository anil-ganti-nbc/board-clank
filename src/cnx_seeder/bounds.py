"""Run bounds for the CNX OEM seeder. Tests assert these values."""

from __future__ import annotations

FEED_URL = "https://www.cnx-software.com/news/sbc/feed/"
LISTING_URL = "https://www.cnx-software.com/news/sbc/"
MAX_LISTING_PAGES = 2
MAX_ARTICLES = 20
MAX_OEM_FETCHES_PER_LEAD = 3
PER_HOST_INTERVAL_SECONDS = 2.0
TIMEOUT_SECONDS = 15
MAX_RETRIES = 1
MAX_BODY_BYTES = 1_500_000
USER_AGENT = (
    "CNXOemSeeder/0.1 (COPS-000080; observation-only; "
    "+https://github.com/anil-ganti-nbc/board-clank)"
)
ROBOTS_TOKEN = "CNXOemSeeder"
ALIAS_TABLE_VERSION = "known-vendors-1"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
ACCESS_CONTROL_STATUSES = frozenset({401, 403, 407, 429})
ARTICLE_PATH_RE = r"^/20[0-9]{2}/[0-9]{2}/[0-9]{2}/[^/]+/?$"
LISTING_PAGE_RE = r"^/news/sbc/page/[0-9]+/?$"
