"""
Central configuration for the news digest bot.

Everything a non-programmer is likely to want to tweak lives in this file:
  - ALLOWED_SOURCES     -> the 6 websites the bot is allowed to read
  - KEYWORD_WEIGHTS      -> every keyword + how important it is (3/2/1)
  - Tunable constants at the bottom (lookback window, digest size, etc.)

Secrets (bot token, user id, timezone) are NOT stored here - they are read
from environment variables in main.py so they never end up in source code.
See README.md for how to set those.
"""

import re

# ---------------------------------------------------------------------------
# 1. ALLOWED SOURCES
# ---------------------------------------------------------------------------
# Each source has:
#   name             - shown next to the article in the Telegram digest
#   homepage         - the page listed in the requirements (used for scraping
#                       fallback and for RSS auto-discovery)
#   feed_candidates  - RSS/Atom URLs to try first, in order. The bot uses the
#                       first one that actually returns articles.
#   scraper          - name of the fallback scraper function in fetchers.py,
#                       used only if none of the feed candidates work.
#
# To add or remove a source: add/remove an entry in this list. Nothing else
# in the code needs to change.
ALLOWED_SOURCES = [
    {
        "id": "aiweekly",
        "name": "AI Weekly",
        "homepage": "https://aiweekly.co/ai-news-today/ai-video-ai-news",
        "feed_candidates": [],  # this page is a live tracker, not a feed
        "scraper": "scrape_aiweekly",
    },
    {
        "id": "digitalcommerce360",
        "name": "Digital Commerce 360",
        "homepage": "https://www.digitalcommerce360.com/",
        "feed_candidates": [
            "https://www.digitalcommerce360.com/feed/",
            "https://www.digitalcommerce360.com/type/news/feed/",
        ],
        "scraper": "scrape_digitalcommerce360",
    },
    {
        "id": "martech",
        "name": "MarTech",
        "homepage": "https://martech.org/",
        "feed_candidates": [
            "https://martech.org/feed/",
        ],
        "scraper": "scrape_generic",
    },
    {
        "id": "socialmediatoday",
        "name": "Social Media Today",
        "homepage": "https://www.socialmediatoday.com/",
        "feed_candidates": [
            "https://www.socialmediatoday.com/feeds/news",
            "https://www.socialmediatoday.com/rss/",
            "https://www.socialmediatoday.com/rss.xml",
        ],
        "scraper": "scrape_generic",
    },
    {
        "id": "searchengineland",
        "name": "Search Engine Land",
        "homepage": "https://searchengineland.com/",
        "feed_candidates": [
            "https://searchengineland.com/feed/",
            "https://searchengineland.com/feed",
        ],
        "scraper": "scrape_generic",
    },
    {
        "id": "marketingaiinstitute",
        "name": "Marketing AI Institute",
        "homepage": "https://www.marketingaiinstitute.com/blog",
        "feed_candidates": [
            "https://www.marketingaiinstitute.com/blog/rss.xml",
            "http://www.marketingaiinstitute.com/blog/rss.xml",
        ],
        "scraper": "scrape_generic",
    },
]

# ---------------------------------------------------------------------------
# 2. KEYWORDS & WEIGHTS
# ---------------------------------------------------------------------------
# Weight tiers. Do not change these numbers unless you also want to change
# how much each tier matters relative to the others.
WEIGHT_HIGH = 3
WEIGHT_MEDIUM = 2
WEIGHT_LOW = 1

# High-value: specific companies / products / platforms / technologies /
# highly specific jargon. These are strong, mostly unambiguous signals.
HIGH_VALUE_KEYWORDS = [
    "TikTok", "Instagram", "Reels", "Facebook", "Meta", "YouTube", "Shorts",
    "Higgsfield", "Nano Banana", "Kling", "Veo", "Sora", "Runway", "Hailuo",
    "Seedance", "Shopify", "1688", "GEO", "UGC-ads", "deminimis",
    "dropservicing", "voice-clone", "lip-sync", "lipsync", "faceswap",
    "img2vid", "demonetization", "shadowban", "Google", "deindexed", "SERP",
    "AI-generated", "LLM", "UGC", "algospeak", "zero-click", "AI-slop",
    "thumbstop",
]

# Medium-value: real industry concepts. Meaningful, but common enough that
# they need supporting context (which the scorer provides via title-vs-body
# placement and by requiring at least one high/medium hit per article).
MEDIUM_VALUE_KEYWORDS = [
    "algorithm", "ranking", "SEO", "indexing", "engagement", "reach",
    "virality", "viral", "dropshipping", "ecommerce", "fulfillment",
    "tariff", "customs", "generative", "deepfake", "moderation",
    "automation", "retention", "branding", "ROAS", "CVR", "divest",
    "ruling", "lawsuit", "crackdown", "shutdown", "outage", "throttle",
    "throttling", "suppress", "boost", "rebrand", "acquired", "organic",
    "crawler", "backlink", "impressions", "hashtag", "discoverability",
    "penalized", "schema", "chargeback", "logistics", "regulation",
    "compliance", "watermark", "disclosure", "labeling", "hallucination",
    "synthetic", "chatbot", "multimodal", "whitelisting", "seeding",
    "faceless",
]

# Low-value: broad, generic words. On their own these should NOT make an
# article relevant - the scorer only counts them as a small bonus, and only
# on articles that already qualified through a high/medium keyword.
LOW_VALUE_KEYWORDS = [
    "ban", "block", "restrict", "bill", "deal", "sale", "sell", "policy",
    "update", "launch", "release", "upgrade", "pricing", "free",
    "unlimited", "waitlist", "changed", "change", "views", "feed",
    "marketplace", "supplier", "wholesaler", "sourcing", "returns",
    "detection", "hook", "fatigue", "saturation", "consistency", "native",
]

def _build_weight_map():
    weight_map = {}
    for kw in HIGH_VALUE_KEYWORDS:
        weight_map[kw] = WEIGHT_HIGH
    for kw in MEDIUM_VALUE_KEYWORDS:
        weight_map[kw] = WEIGHT_MEDIUM
    for kw in LOW_VALUE_KEYWORDS:
        weight_map[kw] = WEIGHT_LOW
    return weight_map

# Final keyword -> weight lookup used by scoring.py
KEYWORD_WEIGHTS = _build_weight_map()

# Pre-compiled case-insensitive, whole-word/phrase regex per keyword.
# Built once at import time so scoring every article is cheap.
def _compile_patterns(weight_map):
    patterns = {}
    for kw in weight_map:
        # Escape the keyword, but keep internal hyphens/spaces intact so
        # multi-word / hyphenated keywords like "voice-clone" or
        # "Nano Banana" still match as a phrase.
        escaped = re.escape(kw)
        patterns[kw] = re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)
    return patterns

KEYWORD_PATTERNS = _compile_patterns(KEYWORD_WEIGHTS)

# ---------------------------------------------------------------------------
# 3. TUNABLE SETTINGS
# ---------------------------------------------------------------------------
DIGEST_SIZE = 25                # max stories per digest
LOOKBACK_HOURS = 48             # articles older than this (when the date is
                                 # known) are excluded outright, not just
                                 # down-ranked - keeps "recent if necessary"
                                 # from turning into "stale filler"
RECENCY_BONUS_MAX = 3.0         # max score bonus for a brand-new article
TITLE_MATCH_MULTIPLIER = 2.5    # a keyword hit in the title counts extra
DEDUP_TITLE_SIMILARITY = 0.72   # 0-1, higher = stricter duplicate matching
HISTORY_RETENTION_DAYS = 45     # how long sent-article records are kept
REQUEST_TIMEOUT_SECONDS = 15
MAX_RETRIES_PER_SOURCE = 2
TELEGRAM_MESSAGE_LIMIT = 4096   # Telegram's hard cap per message
SEND_EMPTY_DIGEST_NOTICE = True  # send a short "nothing new today" message
                                  # instead of staying silent when there are
                                  # zero qualifying stories
DEFAULT_DIGEST_HOUR = 9          # 9 AM local time, overridable via env var
