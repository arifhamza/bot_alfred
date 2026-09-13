"""
The actual "build a digest and send it" pipeline, shared by:
  - webhook_app.py   (real usage: triggered by you typing /ognews)
  - src/main.py        (manual/local testing from your own computer)

Keeping this in one place means the on-demand command and your local test
runs can never drift apart in behavior.
"""

import logging
from datetime import datetime, timezone

from . import config, dedup, fetchers, scoring, storage, telegram_sender

logger = logging.getLogger("digest_bot.builder")

COOLDOWN_SECONDS = config.COOLDOWN_HOURS * 3600


def format_wait_message(seconds_remaining: float) -> str:
    seconds_remaining = max(0, int(seconds_remaining))
    hours, remainder = divmod(seconds_remaining, 3600)
    minutes = remainder // 60
    if hours > 0:
        return f"You can use /ognews again in about {hours}h {minutes}m."
    return f"You can use /ognews again in about {minutes} minute(s)."


def fetch_score_dedup(history: dict):
    """Runs the full pipeline and returns the final ranked list of stories
    (already filtered for relevance, staleness, already-sent, and dupes)."""
    raw_articles = fetchers.fetch_all_sources(config.ALLOWED_SOURCES)
    logger.info("Fetched %d raw articles from %d sources.", len(raw_articles), len(config.ALLOWED_SOURCES))

    fresh_articles = []
    for article in raw_articles:
        if storage.is_already_sent(history, article["url"]):
            continue
        published = article.get("published")
        if published is not None:
            age_hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600.0
            if age_hours > config.LOOKBACK_HOURS:
                continue
        fresh_articles.append(article)
    logger.info("%d articles remain after removing already-sent/stale items.", len(fresh_articles))

    relevant = scoring.score_and_filter(fresh_articles)
    deduped = dedup.deduplicate(relevant)
    final = deduped[: config.DIGEST_SIZE]

    for a in final:
        logger.info("  [%.1f] %s (%s) - keywords: %s", a["score"], a["title"], a["source_name"], ", ".join(a["matched_keywords"]))

    return final


def build_and_send(bot_token: str, chat_id: str, history_path: str, enforce_cooldown: bool = True, dry_run: bool = False):
    """Runs the whole pipeline and sends the result to Telegram.

    Returns (status, detail):
      status == "cooldown" -> detail is the wait message to send the user
      status == "dry_run"  -> detail describes what would have been sent
      status == "sent"     -> detail is a short summary
      status == "error"    -> detail explains what went wrong
    """
    history = storage.load_history(history_path)

    if enforce_cooldown:
        elapsed = storage.seconds_since_last_command(history)
        if elapsed is not None and elapsed < COOLDOWN_SECONDS:
            return "cooldown", format_wait_message(COOLDOWN_SECONDS - elapsed)

    final_articles = fetch_score_dedup(history)

    if dry_run:
        return "dry_run", f"{len(final_articles)} stories would be sent (nothing sent, nothing saved)."

    now_label = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ok = telegram_sender.send_digest(bot_token, chat_id, final_articles, now_label)

    if not ok:
        logger.error("Sending failed - history will NOT be updated so nothing is lost.")
        return "error", "Telegram send failed - see logs."

    if final_articles:
        storage.mark_sent(history, [a["url"] for a in final_articles], datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    removed = storage.prune_old_entries(history, config.HISTORY_RETENTION_DAYS)
    if removed:
        logger.info("Pruned %d history entries older than %d days.", removed, config.HISTORY_RETENTION_DAYS)
    storage.mark_command_used(history)
    storage.save_history(history_path, history)

    return "sent", f"{len(final_articles)} stories sent."
