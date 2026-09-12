"""
Detects duplicate or substantially-identical stories, e.g. the same event
covered by two of the allowed sources, or the same article picked up
twice by different feeds.

Approach:
  - Exact match: same (normalized) URL -> always a duplicate.
  - Near match: normalized titles are compared with difflib's
    SequenceMatcher; above DEDUP_TITLE_SIMILARITY they're treated as the
    same story.

Articles must already be sorted best-score-first before calling
deduplicate() - it keeps the FIRST (i.e. highest-scoring / strongest)
version of each duplicate cluster and discards the rest, which matches
the requirement to "prefer the strongest/original/reliable report."
"""

import re
from difflib import SequenceMatcher

from . import config


def _normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"[^a-z0-9\s]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _normalize_url(url: str) -> str:
    url = url.strip().split("?")[0].split("#")[0].rstrip("/")
    return url.replace("http://", "https://").lower()


def _titles_similar(a: str, b: str) -> bool:
    ratio = SequenceMatcher(None, a, b).ratio()
    return ratio >= config.DEDUP_TITLE_SIMILARITY


def deduplicate(articles: list) -> list:
    kept = []
    kept_urls = set()
    kept_norm_titles = []

    for article in articles:
        norm_url = _normalize_url(article["url"])
        norm_title = _normalize_title(article["title"])

        if norm_url in kept_urls:
            continue

        is_duplicate = any(_titles_similar(norm_title, existing) for existing in kept_norm_titles)
        if is_duplicate:
            continue

        kept.append(article)
        kept_urls.add(norm_url)
        kept_norm_titles.append(norm_title)

    return kept
