"""
Entry point. This is what the GitHub Actions workflow (and you, locally,
for testing) runs.

Environment variables it reads:
    TELEGRAM_BOT_TOKEN   (required)  - your bot's token from BotFather
    TELEGRAM_USER_ID     (required)  - your numeric Telegram user id
    TIMEZONE             (optional)  - IANA name, e.g. "America/New_York".
                                        Defaults to "UTC".
    DIGEST_HOUR           (optional) - local hour (0-23) to send at.
                                        Defaults to 9.
    FORCE_RUN             (optional) - set to "1" to ignore the
                                        hour/already-sent checks. Useful
                                        for manual testing.
    DRY_RUN                (optional) - set to "1" to build and log the
                                        digest without calling Telegram
                                        and without updating history.
                                        Useful for tuning keywords safely.

Exit codes:
    0 - ran successfully (whether or not it was actually "digest time")
    1 - a required setting was missing, or an unexpected error occurred
"""

import logging
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import config, dedup, fetchers, scoring, storage, telegram_sender
from .logging_setup import setup_logging

HISTORY_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sent_history.json")


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip() in ("1", "true", "True", "yes")


def _env_int(name: str, default: int) -> int:
    """Reads an int from the environment. Treats a missing OR an empty
    (but present) variable as 'use the default' - GitHub Actions sets
    unset repository variables to an empty string rather than omitting
    them, so this guards against that."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logging.getLogger("digest_bot.main").warning(
            "%s='%s' is not a valid integer, using default %d instead.", name, raw, default
        )
        return default


def _get_local_now(tz_name: str):
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        raise SystemExit(
            f"TIMEZONE '{tz_name}' is not a recognized IANA timezone name "
            f"(e.g. 'America/New_York', 'Europe/Riga', 'Asia/Tokyo'). "
            f"See README.md for how to find yours."
        )
    return datetime.now(timezone.utc).astimezone(tz)


def main():
    logger = setup_logging()
    logger.info("=== Daily news digest bot starting ===")

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_USER_ID", "").strip()
    tz_name = os.environ.get("TIMEZONE", "UTC").strip() or "UTC"
    digest_hour = _env_int("DIGEST_HOUR", config.DEFAULT_DIGEST_HOUR)
    force_run = _env_flag("FORCE_RUN")
    dry_run = _env_flag("DRY_RUN")

    if not bot_token or not chat_id:
        logger.critical(
            "TELEGRAM_BOT_TOKEN and/or TELEGRAM_USER_ID are not set. "
            "Set them as GitHub Actions secrets (see README.md, section "
            "'Entering your Telegram credentials')."
        )
        sys.exit(1)

    local_now = _get_local_now(tz_name)
    local_date_str = local_now.strftime("%Y-%m-%d")
    logger.info("Local time in %s is %s (target hour: %02d:00).", tz_name, local_now.strftime("%Y-%m-%d %H:%M"), digest_hour)

    history = storage.load_history(HISTORY_PATH)

    if not force_run:
        if local_now.hour != digest_hour:
            logger.info("Not the configured digest hour yet, skipping this run.")
            sys.exit(0)
        if storage.already_sent_today(history, local_date_str):
            logger.info("Digest for %s was already sent, skipping.", local_date_str)
            sys.exit(0)
    else:
        logger.info("FORCE_RUN is set - skipping the hour/already-sent checks.")

    # 1. Fetch --------------------------------------------------------------
    logger.info("Fetching articles from %d sources...", len(config.ALLOWED_SOURCES))
    raw_articles = fetchers.fetch_all_sources(config.ALLOWED_SOURCES)
    logger.info("Fetched %d raw articles total.", len(raw_articles))

    # 2. Drop already-sent and stale articles --------------------------------
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

    # 3. Score + filter for relevance ----------------------------------------
    relevant_articles = scoring.score_and_filter(fresh_articles)

    # 4. Deduplicate (keeps highest-scoring version of each story) ----------
    deduped_articles = dedup.deduplicate(relevant_articles)
    logger.info("%d articles remain after deduplication.", len(deduped_articles))

    # 5. Take the top N ------------------------------------------------------
    final_articles = deduped_articles[: config.DIGEST_SIZE]
    logger.info("Selected %d stories for today's digest.", len(final_articles))

    for a in final_articles:
        logger.info("  [%.1f] %s (%s) - keywords: %s", a["score"], a["title"], a["source_name"], ", ".join(a["matched_keywords"]))

    if dry_run:
        logger.info("DRY_RUN is set - not sending to Telegram and not updating history.")
        sys.exit(0)

    if not final_articles and not config.SEND_EMPTY_DIGEST_NOTICE:
        logger.info("No relevant stories and SEND_EMPTY_DIGEST_NOTICE is off - nothing to send.")
        storage.mark_sent(history, [], local_date_str)
        storage.save_history(HISTORY_PATH, history)
        sys.exit(0)

    # 6. Send -----------------------------------------------------------------
    success = telegram_sender.send_digest(bot_token, chat_id, final_articles, local_date_str)
    if not success:
        logger.error("One or more Telegram messages failed to send. History will NOT be updated so nothing is lost - it will be retried next run.")
        sys.exit(1)

    # 7. Persist history --------------------------------------------------------
    storage.mark_sent(history, [a["url"] for a in final_articles], local_date_str)
    removed = storage.prune_old_entries(history, config.HISTORY_RETENTION_DAYS)
    if removed:
        logger.info("Pruned %d history entries older than %d days.", removed, config.HISTORY_RETENTION_DAYS)
    storage.save_history(HISTORY_PATH, history)

    logger.info("=== Done: digest sent with %d stories ===", len(final_articles))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - top-level safety net so the run's
        # failure is clearly logged instead of a bare traceback.
        logging_logger = setup_logging()
        logging_logger.critical("Unhandled error - see traceback below.", exc_info=True)
        sys.exit(1)
