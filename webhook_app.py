"""
Telegram webhook receiver for the /ognews command - LIGHTWEIGHT VERSION.

This app does NOT fetch any news sites itself (PythonAnywhere's free tier
blocks outbound requests to ordinary websites). Instead, it does one
small thing: tells GitHub Actions to run the real job (fetching, scoring,
deduplicating, sending to Telegram) via the GitHub API - GitHub's
runners have unrestricted internet access, so that's where the actual
work happens.

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

import logging
import os
import re

import requests
from flask import Flask, jsonify, request

from src.telegram_sender import send_telegram_message
from src.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger("digest_bot.webhook")

app = Flask(__name__)

COMMAND_PATTERN = re.compile(r"^/ognews(@\w+)?\b", re.IGNORECASE)


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
            "Send /ognews any time to get the latest relevant stories",
        )
        return jsonify(ok=True)

    if not COMMAND_PATTERN.match(text):
        return jsonify(ok=True)

    logger.info("Received /ognews from %s.", chat_id)

    ok, detail = _trigger_github_workflow()
    if ok:
        send_telegram_message(
            bot_token, chat_id,
            "Of course, sir. Fetching the news streams now. It should land here in just a minute.",
        )
    else:
        logger.error("Failed to trigger GitHub workflow: %s", detail)
        send_telegram_message(bot_token, chat_id, "Something went wrong starting your digest - check the PythonAnywhere error log")

    return jsonify(ok=True)


@app.route("/", methods=["GET"])
def health_check():
    return "OG News webhook is running. Send /ognews to your Telegram bot to use it."


if __name__ == "__main__":
    app.run(debug=True)
