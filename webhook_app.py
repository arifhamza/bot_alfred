"""
Telegram webhook receiver for the /ognews command - LIGHTWEIGHT VERSION.

This app does NOT fetch any news sites itself anymore (PythonAnywhere's
free tier blocks outbound requests to ordinary websites, which broke the
original design). Instead, it does two small things:

  1. Enforces the 24-hour cooldown using its own local file.
  2. Tells GitHub Actions to run the real job (fetching, scoring,
     deduplicating, sending to Telegram) via the GitHub API - GitHub's
     runners have unrestricted internet access, so that's where all the
     actual work happens now.

Environment variables required (set these directly in your PythonAnywhere
WSGI configuration file - see README.md - never commit real values to
GitHub):
    TELEGRAM_BOT_TOKEN     - your bot's token
    TELEGRAM_USER_ID       - your numeric Telegram user id
    GITHUB_TOKEN            - a GitHub Personal Access Token that can
                              trigger workflow runs on your repo
    GITHUB_REPO              - "yourusername/yourreponame"
    GITHUB_WORKFLOW_FILE       - "ognews.yml" (the file in
                                 .github/workflows/)
"""

import json
import logging
import os
import re
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request

from src.telegram_sender import send_telegram_message
from src.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger("digest_bot.webhook")

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOLDOWN_PATH = os.path.join(BASE_DIR, "data", "webhook_cooldown.json")
COOLDOWN_SECONDS = 24 * 60 * 60

COMMAND_PATTERN = re.compile(r"^/ognews(@\w+)?\b", re.IGNORECASE)


def _load_cooldown():
    if not os.path.exists(COOLDOWN_PATH):
        return {"last_trigger_time": None}
    try:
        with open(COOLDOWN_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"last_trigger_time": None}


def _save_cooldown(data):
    os.makedirs(os.path.dirname(COOLDOWN_PATH), exist_ok=True)
    with open(COOLDOWN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _seconds_since_last_trigger():
    data = _load_cooldown()
    ts = data.get("last_trigger_time")
    if not ts:
        return None
    try:
        last = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - last).total_seconds()


def _mark_triggered():
    _save_cooldown({"last_trigger_time": datetime.now(timezone.utc).isoformat()})


def _format_wait_message(seconds_remaining: float) -> str:
    seconds_remaining = max(0, int(seconds_remaining))
    hours, remainder = divmod(seconds_remaining, 3600)
    minutes = remainder // 60
    if hours > 0:
        return f"You can use /ognews again in about {hours}h {minutes}m."
    return f"You can use /ognews again in about {minutes} minute(s)."


def _trigger_github_workflow():
    """Fires the GitHub Actions workflow via the REST API. Returns
    (success: bool, detail: str)."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPO", "").strip()
    workflow_file = os.environ.get("GITHUB_WORKFLOW_FILE", "ognews.yml").strip()

    if not token or not repo:
        return False, "GITHUB_TOKEN / GITHUB_REPO are not set in this app's environment."

    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"ref": "main"}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
    except requests.RequestException as exc:
        return False, f"Could not reach GitHub: {exc}"

    if resp.status_code == 204:
        return True, "Workflow triggered."
    return False, f"GitHub API returned {resp.status_code}: {resp.text[:300]}"


@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    allowed_chat_id = os.environ.get("TELEGRAM_USER_ID", "").strip()

    if not bot_token or not allowed_chat_id:
        logger.error("TELEGRAM_BOT_TOKEN / TELEGRAM_USER_ID are not set.")
        return jsonify(ok=True)

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
        send_telegram_message(
            bot_token, chat_id,
            "Send /ognews any time to get the latest relevant stories. Limited to once every 24 hours.",
        )
        return jsonify(ok=True)

    if not COMMAND_PATTERN.match(text):
        return jsonify(ok=True)

    logger.info("Received /ognews from %s.", chat_id)

    elapsed = _seconds_since_last_trigger()
    if elapsed is not None and elapsed < COOLDOWN_SECONDS:
        wait_msg = _format_wait_message(COOLDOWN_SECONDS - elapsed)
        send_telegram_message(bot_token, chat_id, wait_msg)
        return jsonify(ok=True)

    ok, detail = _trigger_github_workflow()
    if ok:
        _mark_triggered()
        send_telegram_message(bot_token, chat_id, "On it - building your digest now, should land in under a minute.")
    else:
        logger.error("Failed to trigger GitHub workflow: %s", detail)
        send_telegram_message(bot_token, chat_id, "Something went wrong starting your digest - check the PythonAnywhere error log.")

    return jsonify(ok=True)


@app.route("/", methods=["GET"])
def health_check():
    return "OG News webhook is running. Send /ognews to your Telegram bot to use it."


if __name__ == "__main__":
    app.run(debug=True)
