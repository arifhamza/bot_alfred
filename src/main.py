"""
Manual/local test entry point - NOT used by the live bot anymore.

The live bot is webhook_app.py, deployed on PythonAnywhere, which answers
/ognews on demand. This script exists so you can test the fetch/score/
dedup/send pipeline from your own computer without needing a deployed
webhook - handy while tuning keywords or sources.

Environment variables it reads:
    TELEGRAM_BOT_TOKEN   (required)
    TELEGRAM_USER_ID     (required)
    IGNORE_COOLDOWN       (optional) - set to "1" to bypass the 24h cooldown
    DRY_RUN                (optional) - set to "1" to build and log the
                                        digest without sending or saving

Exit codes: 0 on success (including "cooldown" - that's not a failure),
1 if credentials are missing or an unexpected error occurred.
"""

import os
import sys

from . import config, digest_builder
from .logging_setup import setup_logging

HISTORY_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sent_history.json")


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip() in ("1", "true", "True", "yes")


def main():
    logger = setup_logging()
    logger.info("=== Manual test run ===")

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_USER_ID", "").strip()
    ignore_cooldown = _env_flag("IGNORE_COOLDOWN")
    dry_run = _env_flag("DRY_RUN")

    if not bot_token or not chat_id:
        logger.critical("TELEGRAM_BOT_TOKEN and/or TELEGRAM_USER_ID are not set.")
        sys.exit(1)

    status, detail = digest_builder.build_and_send(
        bot_token, chat_id, HISTORY_PATH,
        enforce_cooldown=not ignore_cooldown,
        dry_run=dry_run,
    )
    logger.info("Result: %s - %s", status, detail)
    sys.exit(0 if status in ("sent", "dry_run", "cooldown") else 1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        setup_logging().critical("Unhandled error - see traceback below.", exc_info=True)
        sys.exit(1)
