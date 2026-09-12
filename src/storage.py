"""
Lightweight JSON-file storage for:
  - which article URLs have already been sent (so we never repeat one)
  - the local date the digest was last successfully sent (so an hourly
    cron trigger never sends the same day's digest twice)

The file lives at data/sent_history.json inside the repo. The GitHub
Actions workflow commits this file back to the repo after every run, so
history survives between runs even though each run starts on a fresh,
throwaway virtual machine.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("digest_bot.storage")

DEFAULT_HISTORY = {
    "sent_urls": {},     # normalized_url -> ISO date string it was sent
    "last_sent_date": None,  # e.g. "2026-09-12" in the target timezone
}


def _normalize_url(url: str) -> str:
    """Make small formatting differences (trailing slash, http vs https,
    tracking params) not cause duplicate sends."""
    url = url.strip()
    url = url.split("?")[0].split("#")[0]
    url = url.rstrip("/")
    url = url.replace("http://", "https://")
    return url.lower()


def load_history(path: str) -> dict:
    if not os.path.exists(path):
        logger.info("No history file found at %s, starting fresh.", path)
        return dict(DEFAULT_HISTORY)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("sent_urls", {})
        data.setdefault("last_sent_date", None)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Could not read history file (%s), starting fresh: %s", path, exc)
        return dict(DEFAULT_HISTORY)


def save_history(path: str, history: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)
    logger.info("Saved history file with %d tracked URLs.", len(history.get("sent_urls", {})))


def is_already_sent(history: dict, url: str) -> bool:
    return _normalize_url(url) in history.get("sent_urls", {})


def mark_sent(history: dict, urls, sent_date_iso: str) -> None:
    for url in urls:
        history["sent_urls"][_normalize_url(url)] = sent_date_iso
    history["last_sent_date"] = sent_date_iso


def already_sent_today(history: dict, local_date_str: str) -> bool:
    return history.get("last_sent_date") == local_date_str


def prune_old_entries(history: dict, retention_days: int) -> int:
    """Remove sent-URL records older than retention_days to keep the file
    small. Returns the number of entries removed."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = 0
    kept = {}
    for url, date_str in history.get("sent_urls", {}).items():
        try:
            entry_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            # Unparseable date, keep it rather than risk losing dedup info.
            kept[url] = date_str
            continue
        if entry_date >= cutoff:
            kept[url] = date_str
        else:
            removed += 1
    history["sent_urls"] = kept
    return removed
