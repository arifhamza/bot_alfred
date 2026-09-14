# /ognews Telegram News Bot

Type `/ognews` to your Telegram bot any time and get the most relevant
news stories from your 6 chosen sites, ranked and deduplicated. Limited
to once every 24 hours.

## Architecture (why two free services, not one)

| Piece | What it does | Why it's there |
|---|---|---|
| **PythonAnywhere** (`webhook_app.py`) | Listens for your `/ognews` message, enforces the 24h cooldown, and tells GitHub to run the real job | It's the only piece that's always reachable, so Telegram has somewhere to deliver your message to |
| **GitHub Actions** (`.github/workflows/ognews.yml`) | Actually fetches your 6 sites, scores/ranks/dedupes articles, sends the Telegram messages, and saves history | PythonAnywhere's free tier blocks outbound requests to ordinary websites (only official public APIs are allowed) - GitHub's runners have full internet access, confirmed working in earlier testing |

So: **Telegram → PythonAnywhere (gatekeeper) → GitHub Actions (does the work) → Telegram (sends you the result directly)**.

---

## 1. What's in this project

```
telegram-news-digest/
├── webhook_app.py                    <- PythonAnywhere: listens for /ognews
├── .github/workflows/ognews.yml      <- GitHub Actions: does the real work
├── data/sent_history.json            <- memory: sent URLs (git-committed by Actions)
├── requirements.txt                  <- full deps, used by GitHub Actions
├── requirements-webhook.txt          <- light deps (flask+requests), used by PythonAnywhere
├── src/
│   ├── config.py             <- keywords, sources, all settings you'll tweak
│   ├── digest_builder.py       <- the fetch/score/dedup/send pipeline
│   ├── fetchers.py               <- downloads articles (RSS + scrapers)
│   ├── scoring.py                  <- relevance ranking
│   ├── dedup.py                      <- duplicate detection
│   ├── telegram_sender.py              <- formats and sends Telegram messages
│   ├── storage.py                        <- reads/writes the memory file
│   ├── main.py                             <- run by GitHub Actions (and for local testing)
│   └── logging_setup.py                      <- logging configuration
└── README.md
```

## 2. Setup: step by step

### A. Code is on GitHub, public repo (you've done this)

### B. Add the GitHub Actions workflow's secrets (if not already there)

**Settings → Secrets and variables → Actions → Secrets tab**: confirm
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_USER_ID` are set (you set these
earlier - no change needed if so).

### C. Create a GitHub Personal Access Token (new step)

This lets PythonAnywhere tell GitHub "run the workflow now."

1. Go to **github.com → your profile picture → Settings → Developer
   settings → Personal access tokens → Fine-grained tokens → Generate
   new token**.
2. Name it anything, e.g. `ognews-trigger`.
3. **Repository access**: select **Only select repositories** → choose
   your repo.
4. **Permissions**: expand **Repository permissions** → find **Actions**
   → set to **Read and write**.
5. Generate it, and **copy the token immediately** - GitHub only shows it
   once.

### D. On PythonAnywhere: pull the new code

Bash console:
```
cd ~/telegram_bot_news
git pull
pip3.13 install --user -r requirements-webhook.txt
```
(use whichever Python version your web app is actually set to)

### E. Update your WSGI configuration file

Add **three new lines** to the file you already have (keep the existing
`TELEGRAM_BOT_TOKEN` / `TELEGRAM_USER_ID` lines as they are):

```python
os.environ['GITHUB_TOKEN'] = 'paste-your-fine-grained-token-here'
os.environ['GITHUB_REPO'] = 'yourusername/telegram_bot_news'
os.environ['GITHUB_WORKFLOW_FILE'] = 'ognews.yml'
```

Save, go to the **Web** tab, click **Reload**.

### F. Delete the old scheduled workflow, if it's still there

If `.github/workflows/daily-digest.yml` still exists in your repo,
delete it - it's fully replaced by `ognews.yml` now.

## 3. Testing

1. Visit `https://arifm00.pythonanywhere.com/` - should say *"OG News
   webhook is running."*
2. In Telegram, send `/ognews`.
3. You should immediately get: *"On it - building your digest now..."*
4. Within about a minute, a second message arrives with your actual
   stories - that one comes straight from GitHub Actions, not
   PythonAnywhere.
5. Send `/ognews` again right away - should reply with the cooldown
   wait-message instead of triggering another run.
6. You can also watch it happen live: **GitHub repo → Actions tab** -
   you'll see an **"OG News Digest"** run start the moment you message
   the bot.

## 4. Adding/removing keywords and sources

Unchanged - both live in `src/config.py` (`HIGH_VALUE_KEYWORDS` /
`MEDIUM_VALUE_KEYWORDS` / `LOW_VALUE_KEYWORDS`, and `ALLOWED_SOURCES`).
After editing on GitHub, no PythonAnywhere update is needed for these -
GitHub Actions always runs the latest code from your repo automatically.

## 5. How ranking, dedup, and cooldown work

**Ranking**: every keyword has a weight - high (3), medium (2), low (1).
A hit in the title counts 2.5x more than one only in the summary. A
low-value keyword alone can never qualify an article - at least one
high/medium match is required first. Articles older than
`LOOKBACK_HOURS` in `src/config.py` are dropped rather than used as
filler.

**Deduplication**: identical or near-identical URLs/titles are merged,
keeping whichever scored higher. This history lives in
`data/sent_history.json` and is committed back to your repo by GitHub
Actions after every successful send.

**Cooldown**: PythonAnywhere tracks the last trigger time in its own
small local file and refuses new requests within `COOLDOWN_HOURS` (24 by
default, set in `src/config.py`) of the last one.

## 6. Troubleshooting

**No "On it..." message at all when you send /ognews**
- Check `https://arifm00.pythonanywhere.com/` loads.
- Check PythonAnywhere's **Web tab → error log**.
- Confirm the webhook is registered (revisit the `setWebhook` URL from
  earlier - should say `"ok":true`).

**Got "On it..." but no digest ever arrives**
- Go to the **Actions** tab on GitHub - did a run actually start? If
  not, the GitHub API call failed - check the PythonAnywhere error log
  for a message starting with "Failed to trigger GitHub workflow."
  Common causes: the fine-grained token wasn't given **Actions: Read and
  write** permission, `GITHUB_REPO` is misspelled, or the token expired.
- If a run *did* start but shows a red X, click into it and read the
  log - same troubleshooting as before (missing secrets, a source
  failing, etc.).

**"0 relevant stories" every time**
- This was the PythonAnywhere allow-list problem from before - now that
  fetching happens in GitHub Actions instead, it shouldn't recur. If it
  does, check whether the run actually found articles (open the Actions
  log and look for lines like "Fetched N raw articles").

## 7. Known limitations

- **PythonAnywhere free tier can't reach ordinary websites** - this is
  why the split-architecture exists; don't add fetching logic back into
  `webhook_app.py` without also either upgrading PythonAnywhere or
  getting each specific domain allow-listed (unlikely to be approved,
  since PythonAnywhere only allow-lists official public APIs).
- **Two systems means two places to check when debugging** - the
  PythonAnywhere error log (for anything before the digest starts
  building) and the GitHub Actions log (for anything after).
- **The Personal Access Token expires** if you set an expiration date
  when creating it - if `/ognews` suddenly stops triggering GitHub after
  working fine for a while, check whether the token needs renewing.
- **Cooldown is a rolling 24 hours from your last use**, not tied to a
  calendar day.
