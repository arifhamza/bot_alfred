"""
Telegram webhook receiver for the /ognews command.

This is the piece that makes typing /ognews in Telegram actually do
something. It is a small always-on web app (deployed for free on
PythonAnywhere - see README.md, "Deploying /ognews"). Telegram pushes an
HTTP POST here every time a message is sent to your bot; this app checks
whether it was "/ognews", and if the 24-hour cooldown has passed, runs
the same fetch -> score -> dedup pipeline the project has always used and
sends the result back.

Environment variables required (set these directly in your PythonAnywhere
WSGI configuration file, NOT in this source file or in GitHub - see
README.md):
    TELEGRAM_BOT_TOKEN
    TELEGRAM_USER_ID
"""

import logging
import os
import re

from flask import Flask, jsonify, request

from src import digest_builder, telegram_sender
from src.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger("digest_bot.webhook")

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(BASE_DIR, "data", "sent_history.json")

# Matches "/ognews" and also Telegram's "/ognews@YourBotName" form.
COMMAND_PATTERN = re.compile(r"^/ognews(@\w+)?\b", re.IGNORECASE)


def _get_credentials():
    return (
        os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        os.environ.get("TELEGRAM_USER_ID", "").strip(),
    )


@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    bot_token, allowed_chat_id = _get_credentials()
    if not bot_token or not allowed_chat_id:
        logger.error("TELEGRAM_BOT_TOKEN / TELEGRAM_USER_ID are not set in this app's environment.")
        return jsonify(ok=True)  # still 200, so Telegram doesn't retry-storm us

    update = request.get_json(silent=True) or {}
    message = update.get("message") or update.get("edited_message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id", ""))

    if not chat_id:
        return jsonify(ok=True)

    if chat_id != allowed_chat_id:
        logger.info("Ignoring a message from an unrecognized chat id.")
        return jsonify(ok=True)

    if text.lower().startswith("/start"):
        telegram_sender.send_telegram_message(
            bot_token, chat_id,
            "Send /ognews any time to get the latest relevant stories. Limited to once every 24 hours.",
        )
        return jsonify(ok=True)

    if not COMMAND_PATTERN.match(text):
        return jsonify(ok=True)  # not our command, ignore silently

    logger.info("Received /ognews from %s.", chat_id)
    status, detail = digest_builder.build_and_send(bot_token, chat_id, HISTORY_PATH)

    if status == "cooldown":
        telegram_sender.send_telegram_message(bot_token, chat_id, detail)
    elif status == "error":
        telegram_sender.send_telegram_message(
            bot_token, chat_id,
            "Something went wrong building your digest. Check the PythonAnywhere error log for details.",
        )
    # status == "sent" -> digest_builder already sent the messages itself.

    return jsonify(ok=True)


@app.route("/", methods=["GET"])
def health_check():
    """Visiting your PythonAnywhere URL in a browser should show this -
    it's just a quick way to confirm the app is deployed and running."""
    return "News digest bot webhook is running. Send /ognews to your Telegram bot to use it."


if __name__ == "__main__":
    # Only used if you ever run this directly for local testing - on
    # PythonAnywhere, the WSGI configuration imports `app` instead.
    app.run(debug=True)
