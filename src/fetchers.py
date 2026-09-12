"""
Turns each configured source into a list of "raw article" dicts:

    {
        "title": str,
        "url": str,              # absolute URL
        "summary": str,          # short snippet, may be ""
        "published": datetime | None,   # timezone-aware UTC, or None
        "source_id": str,
        "source_name": str,
    }

Strategy per source (in order):
  1. Try each configured RSS/Atom feed candidate.
  2. If none of those work, try to auto-discover a feed by looking for
     <link rel="alternate" type="application/rss+xml"> on the homepage.
  3. If no feed can be found or parsed, fall back to the source-specific
     HTML scraper registered in config.py (falls back further to a
     generic scraper for sources that don't have a custom one).

Every network call is wrapped in retries + timeouts, and a failure on one
source never stops the others (requirement: "continue working if one
source temporarily fails").
"""

import logging
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests
from bs4 import BeautifulSoup

from . import config

logger = logging.getLogger("digest_bot.fetchers")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PersonalNewsDigestBot/1.0; "
        "+https://github.com/) - single-user personal RSS digest"
    )
}


def _get(url: str):
    """GET a URL with retries + timeout. Returns the Response or None."""
    last_exc = None
    for attempt in range(1, config.MAX_RETRIES_PER_SOURCE + 2):
        try:
            resp = requests.get(
                url, headers=HEADERS, timeout=config.REQUEST_TIMEOUT_SECONDS
            )
            if resp.status_code == 200:
                return resp
            logger.warning("GET %s returned HTTP %s (attempt %d)", url, resp.status_code, attempt)
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning("GET %s failed (attempt %d): %s", url, attempt, exc)
        time.sleep(1.5 * attempt)  # small backoff before retrying
    if last_exc:
        logger.error("Giving up on %s: %s", url, last_exc)
    return None


def _parse_date_safe(value) -> "datetime | None":
    """Best-effort parsing of a date coming from RSS or scraped HTML into
    a timezone-aware UTC datetime. Returns None if it can't be parsed -
    callers treat that as 'unknown, assume worth considering'."""
    if value is None:
        return None
    if isinstance(value, time.struct_time):
        try:
            return datetime(*value[:6], tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        # Try RFC 822 (common RSS pubDate format)
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (TypeError, ValueError, IndexError):
            pass
        # Try plain ISO format (2026-09-10 or 2026-09-10T12:00:00)
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
        # Try YYYY/MM/DD (used inside some URLs)
        m = re.match(r"(\d{4})/(\d{1,2})/(\d{1,2})", value)
        if m:
            try:
                y, mo, d = (int(x) for x in m.groups())
                return datetime(y, mo, d, tzinfo=timezone.utc)
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------------------
# RSS handling
# ---------------------------------------------------------------------------
def _try_feed_url(feed_url: str):
    resp = _get(feed_url)
    if resp is None:
        return None
    parsed = feedparser.parse(resp.content)
    if not parsed.entries:
        return None
    return parsed


def _discover_feed_links(homepage_url: str):
    """Look at a page's <head> for <link rel="alternate" type="rss/atom">
    tags and return any feed URLs found (absolute)."""
    resp = _get(homepage_url)
    if resp is None:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    found = []
    for link in soup.find_all("link", rel="alternate"):
        type_attr = (link.get("type") or "").lower()
        if "rss" in type_attr or "atom" in type_attr:
            href = link.get("href")
            if href:
                found.append(requests.compat.urljoin(homepage_url, href))
    return found


def _entries_to_articles(parsed_feed, source_id: str, source_name: str):
    articles = []
    for entry in parsed_feed.entries:
        title = (entry.get("title") or "").strip()
        url = (entry.get("link") or "").strip()
        if not title or not url:
            continue
        summary = (entry.get("summary") or entry.get("description") or "")
        # Strip any HTML tags that sneak into RSS summaries.
        summary = BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)
        published = _parse_date_safe(entry.get("published_parsed") or entry.get("updated_parsed"))
        articles.append(
            {
                "title": title,
                "url": url,
                "summary": summary[:500],
                "published": published,
                "source_id": source_id,
                "source_name": source_name,
            }
        )
    return articles


def fetch_via_rss(source: dict):
    """Try every configured feed candidate, then auto-discovery, in order.
    Returns a list of articles, or None if no feed could be used at all."""
    candidates = list(source.get("feed_candidates", []))

    for feed_url in candidates:
        parsed = _try_feed_url(feed_url)
        if parsed:
            logger.info("[%s] RSS feed OK: %s (%d entries)", source["id"], feed_url, len(parsed.entries))
            return _entries_to_articles(parsed, source["id"], source["name"])

    # Nothing in the hardcoded list worked - try auto-discovery.
    discovered = _discover_feed_links(source["homepage"])
    for feed_url in discovered:
        if feed_url in candidates:
            continue
        parsed = _try_feed_url(feed_url)
        if parsed:
            logger.info("[%s] auto-discovered RSS feed OK: %s (%d entries)", source["id"], feed_url, len(parsed.entries))
            return _entries_to_articles(parsed, source["id"], source["name"])

    return None


# ---------------------------------------------------------------------------
# Source-specific scrapers (used only when RSS isn't available)
# ---------------------------------------------------------------------------
def scrape_aiweekly(source: dict):
    """AI Weekly's topic-tracker page lists 'Live Stories' as:
    [Title](https://aiweekly.co/alerts/<slug>)  followed by
    'sourcedomain.com · YYYY-MM-DD · Score: NN'.
    We match on the distinctive /alerts/ link prefix rather than on CSS
    classes, since that structural pattern is less likely to change than
    styling.
    """
    resp = _get(source["homepage"])
    if resp is None:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    seen_urls = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/alerts/" not in href:
            continue
        url = requests.compat.urljoin(source["homepage"], href)
        if url in seen_urls:
            continue
        title = a.get_text(strip=True)
        if not title:
            continue
        # The date/source line usually sits in the same list item as the
        # link. Look at the surrounding text for a "YYYY-MM-DD" pattern.
        container_text = ""
        parent = a.find_parent()
        if parent:
            container_text = parent.get_text(" ", strip=True)
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", container_text)
        published = _parse_date_safe(date_match.group(1)) if date_match else None
        seen_urls.add(url)
        articles.append(
            {
                "title": title,
                "url": url,
                "summary": "",
                "published": published,
                "source_id": source["id"],
                "source_name": source["name"],
            }
        )
    return articles


def scrape_digitalcommerce360(source: dict):
    """Digital Commerce 360's main news-listing page ('/type/news/') is
    loaded via JavaScript, so we instead scrape the two server-rendered
    vertical landing pages, and pull the publish date directly out of the
    article URL, which always follows /YYYY/MM/DD/slug/.
    """
    listing_pages = [
        "https://www.digitalcommerce360.com/internet-retailer/",
        "https://www.digitalcommerce360.com/b2b-ecommerce-world/",
    ]
    url_pattern = re.compile(
        r"^https://www\.digitalcommerce360\.com/(\d{4})/(\d{2})/(\d{2})/[^/]+/?$"
    )
    articles = []
    seen_urls = set()
    for page in listing_pages:
        resp = _get(page)
        if resp is None:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            m = url_pattern.match(href)
            if not m:
                continue
            title = a.get_text(strip=True)
            if not title or len(title) < 8:
                continue  # skip nav/image-only links with no real title
            if href in seen_urls:
                continue
            seen_urls.add(href)
            y, mo, d = (int(x) for x in m.groups())
            try:
                published = datetime(y, mo, d, tzinfo=timezone.utc)
            except ValueError:
                published = None
            articles.append(
                {
                    "title": title,
                    "url": href,
                    "summary": "",
                    "published": published,
                    "source_id": source["id"],
                    "source_name": source["name"],
                }
            )
    return articles


def scrape_generic(source: dict):
    """Fallback scraper for any source without a custom one, or when a
    source's RSS feed is unexpectedly unavailable. Looks for heading tags
    (h1-h3) that wrap a same-domain link with real link text, which is
    the most common pattern for news/blog listing pages regardless of the
    specific theme or CSS framework in use."""
    resp = _get(source["homepage"])
    if resp is None:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    domain = requests.utils.urlparse(source["homepage"]).netloc.replace("www.", "")

    articles = []
    seen_urls = set()
    for heading in soup.find_all(["h1", "h2", "h3"]):
        a = heading.find("a", href=True)
        if not a:
            continue
        href = a["href"].strip()
        url = requests.compat.urljoin(source["homepage"], href)
        link_domain = requests.utils.urlparse(url).netloc.replace("www.", "")
        if domain not in link_domain:
            continue  # skip off-site links (ads, social icons, etc.)
        title = a.get_text(strip=True)
        if not title or len(title) < 8:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Look for a nearby <time datetime="..."> for the publish date.
        published = None
        container = heading.find_parent(["article", "li", "div"]) or heading
        time_tag = container.find("time") if container else None
        if time_tag and time_tag.get("datetime"):
            published = _parse_date_safe(time_tag["datetime"])

        articles.append(
            {
                "title": title,
                "url": url,
                "summary": "",
                "published": published,
                "source_id": source["id"],
                "source_name": source["name"],
            }
        )
    return articles


SCRAPERS = {
    "scrape_aiweekly": scrape_aiweekly,
    "scrape_digitalcommerce360": scrape_digitalcommerce360,
    "scrape_generic": scrape_generic,
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def fetch_source(source: dict):
    """Fetch articles for one source, trying RSS first and falling back to
    scraping. Never raises - returns [] on total failure so one broken
    source can't take down the whole run."""
    try:
        if source.get("feed_candidates"):
            articles = fetch_via_rss(source)
            if articles:
                return articles
            logger.warning("[%s] no usable RSS feed, falling back to scraping.", source["id"])

        scraper_name = source.get("scraper", "scrape_generic")
        scraper_fn = SCRAPERS.get(scraper_name, scrape_generic)
        articles = scraper_fn(source)
        logger.info("[%s] scraper produced %d articles.", source["id"], len(articles))
        return articles
    except Exception as exc:  # noqa: BLE001 - a single bad source must not crash the run
        logger.error("[%s] fetch failed entirely: %s", source["id"], exc, exc_info=True)
        return []


def fetch_all_sources(sources):
    """Fetch every configured source. Returns a flat list of article dicts.
    Logs a per-source summary and keeps going even if some sources fail."""
    all_articles = []
    for source in sources:
        articles = fetch_source(source)
        all_articles.extend(articles)
    return all_articles
