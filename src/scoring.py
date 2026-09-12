"""
Scores each article for relevance to the configured keyword interests.

Design (see README.md "How ranking works" for the plain-English version):

  - Every keyword has a weight: high=3, medium=2, low=1 (config.py).
  - A keyword match in the TITLE counts more than a match only in the
    summary/snippet, since the title is the strongest signal of what an
    article is actually about.
  - Low-value keywords (very broad words like "free", "update", "launch")
    can NEVER qualify an article on their own. An article must contain at
    least one HIGH or MEDIUM keyword match to be considered relevant at
    all. This directly implements the requirement that broad keywords
    "should not independently make an article highly relevant."
  - Once an article qualifies, low-value keyword matches add a small extra
    bonus, since they can reinforce genuine relevance (e.g. a TikTok
    article that also mentions "ban" is more likely to matter than one
    that doesn't).
  - A recency bonus rewards newer articles.

This is a transparent, deterministic heuristic - not full language
understanding. It is intentionally conservative: when in doubt, an
article without a specific/medium keyword hit is dropped rather than
guessed into the digest.
"""

import logging
from datetime import datetime, timezone

from . import config

logger = logging.getLogger("digest_bot.scoring")


def _keyword_hits(text: str, patterns: dict):
    """Return the set of keywords whose pattern matches somewhere in text."""
    hits = set()
    if not text:
        return hits
    for kw, pattern in patterns.items():
        if pattern.search(text):
            hits.add(kw)
    return hits


def _recency_bonus(published):
    if published is None:
        return 0.0
    now = datetime.now(timezone.utc)
    hours_old = max(0.0, (now - published).total_seconds() / 3600.0)
    if hours_old >= config.LOOKBACK_HOURS:
        return 0.0
    fraction_remaining = 1.0 - (hours_old / config.LOOKBACK_HOURS)
    return round(config.RECENCY_BONUS_MAX * fraction_remaining, 2)


def score_article(article: dict):
    """Returns (score: float, matched_keywords: list[str]).
    score == 0.0 means 'not relevant, exclude from the digest'."""
    title = article.get("title") or ""
    summary = article.get("summary") or ""

    title_hits = _keyword_hits(title, config.KEYWORD_PATTERNS)
    summary_hits = _keyword_hits(summary, config.KEYWORD_PATTERNS) - title_hits

    all_hits = title_hits | summary_hits
    if not all_hits:
        return 0.0, []

    has_qualifying_hit = any(config.KEYWORD_WEIGHTS[kw] >= config.WEIGHT_MEDIUM for kw in all_hits)
    if not has_qualifying_hit:
        # Only low-value keywords matched anywhere - not enough on its own.
        return 0.0, []

    score = 0.0
    for kw in title_hits:
        score += config.KEYWORD_WEIGHTS[kw] * config.TITLE_MATCH_MULTIPLIER
    for kw in summary_hits:
        score += config.KEYWORD_WEIGHTS[kw] * 1.0

    score += _recency_bonus(article.get("published"))

    return round(score, 2), sorted(all_hits)


def score_and_filter(articles):
    """Scores every article, drops non-relevant ones (score == 0), and
    returns the relevant ones sorted highest-score-first."""
    scored = []
    for article in articles:
        score, matched = score_article(article)
        if score <= 0:
            continue
        enriched = dict(article)
        enriched["score"] = score
        enriched["matched_keywords"] = matched
        scored.append(enriched)

    scored.sort(key=lambda a: a["score"], reverse=True)
    logger.info("Scored %d/%d fetched articles as relevant.", len(scored), len(articles))
    return scored
