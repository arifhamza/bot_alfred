# /ognews Telegram News Bot

Type `/ognews` to your Telegram bot any time and get the most relevant
news stories from your 6 chosen sites, ranked and deduplicated. Limited
to once every 24 hours. No scheduling, no server bills.

This version replaced an earlier scheduled-digest design - see
[section 6](#6-why-pythonanywhere-instead-of-github-actions) for why an
on-demand command needs different hosting than a daily cron job.

---

## Contents

1. [How it works](#1-how-it-works)
2. [What's in this project](#2-whats-in-this-project)
3. [Setup: step by step](#3-setup-step-by-step)
4. [Testing](#4-testing)
5. [Adding/removing keywords and sources](#5-addingremoving-keywords-and-sources)
6. [Why PythonAnywhere instead of GitHub Actions](#6-why-pythonanywhere-instead-of-github-actions)
7. [How the ranking and cooldown work](#7-how-the-ranking-and-cooldown-work)
8. [Updating the code later](#8-updating-the-code-later)
9. [Troubleshooting](#9-troubleshooting)
10. [Known limitations](#10-known-limitations)

---

## 1. How it works

1. You type `/ognews` to your bot in Telegram.
2. Telegram instantly forwards that message to a small always-on web app
   (`webhook_app.py`) hosted for free on PythonAnywhere.
3. That app checks: has it been at least 24 hours since you last used
   `/ognews`? If not, it replies telling you how long to wait, and stops.
4. If you're clear, it fetches your 6 sites, scores every article against
   your keywords, drops anything already sent before, removes near-dupes,
   and sends you up to 25 of the best ones.
5. It remembers what it sent (in a local file on the PythonAnywhere
   account) so those same stories never come back.

There is no scheduler and no daily automatic send anymore - it only runs
when you ask it to.

## 2. What's in this project

```
telegram-news-digest/
├── webhook_app.py            <- the live bot: listens for /ognews
├── data/sent_history.json    <- memory: sent URLs + cooldown timestamp
├── src/
│   ├── config.py               <- keywords, sources, all settings you'll tweak
│   ├── digest_builder.py         <- the shared fetch/score/dedup/send pipeline
│   ├── fetchers.py                 <- downloads articles (RSS + scrapers)
│   ├── scoring.py                    <- relevance ranking
│   ├── dedup.py                        <- duplicate detection
│   ├── telegram_sender.py                <- formats and sends Telegram messages
│   ├── storage.py                          <- reads/writes the memory file
│   ├── main.py                               <- optional: manual/local test runner
│   └── logging_setup.py                        <- logging configuration
├── requirements.txt          <- the 4 Python packages it needs
└── README.md
```

## 3. Setup: step by step

### A. Get the code into GitHub (skip if you already did this)

Same as before - create a free GitHub account, create a public repo, and
upload this folder (Add file → Upload files, dragging the whole folder
in). Public keeps things simple and free; your bot token is never stored
in this repo regardless.

### B. Create a free PythonAnywhere account

Go to [pythonanywhere.com](https://www.pythonanywhere.com) → **Pricing &
signup** → **Create a Beginner account** (free, no credit card).

### C. Get the code onto PythonAnywhere

1. On your PythonAnywhere dashboard, open a **Bash console** (Consoles
   tab → **Bash**).
2. Run:
   ```
   git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
   cd YOUR_REPO_NAME
   pip3.10 install --user -r requirements.txt
   ```
   (If `pip3.10` isn't found, run `python3 --version` to see what's
   available and use the matching `pip3.x`.)

### D. Create the web app

1. Go to the **Web** tab → **Add a new web app** → **Next**.
2. Choose **Manual configuration** (not the Flask wizard - we already
   have our own app).
3. Pick the Python version matching what you installed packages for.
4. PythonAnywhere creates your app at `https://YOUR_USERNAME.pythonanywhere.com`.

### E. Point it at your code and add your credentials

1. Still on the **Web** tab, find **WSGI configuration file** and click
   its path to open it in the editor.
2. Delete everything in that file and replace it with:
   ```python
   import sys
   import os

   project_home = '/home/YOUR_USERNAME/YOUR_REPO_NAME'
   if project_home not in sys.path:
       sys.path.insert(0, project_home)

   os.environ['TELEGRAM_BOT_TOKEN'] = 'paste-your-real-token-here'
   os.environ['TELEGRAM_USER_ID'] = 'paste-your-real-user-id-here'

   from webhook_app import app as application
   ```
3. Replace `YOUR_USERNAME`, `YOUR_REPO_NAME`, and the two credential
   values with your real ones. **This file lives only on your
   PythonAnywhere account, never in GitHub** - this is the one and only
   place your real token goes.
4. Save, go back to the **Web** tab, and click the big green **Reload**
   button.
5. Visit `https://YOUR_USERNAME.pythonanywhere.com/` in a browser - you
   should see: *"News digest bot webhook is running."* That confirms
   deployment worked.

### F. Tell Telegram where to send your messages

Visit this URL in any browser (replace both placeholders):

```
https://api.telegram.org/botYOUR_BOT_TOKEN/setWebhook?url=https://YOUR_USERNAME.pythonanywhere.com/telegram-webhook
```

You should see `{"ok":true,"result":true,"description":"Webhook was set"}`.
That's it - Telegram now pushes your messages straight to your bot.

## 4. Testing

1. Open your bot in Telegram, press **Start** (required once).
2. Send `/ognews`.
3. Wait 10-30 seconds (it's actually fetching 6 sites live) - you should
   get a header message plus your ranked stories.
4. Send `/ognews` again immediately - you should get *"You can use
   /ognews again in about 23h 59m"* instead of a second digest. That
   confirms the cooldown works.

If nothing happens at all, see [Troubleshooting](#9-troubleshooting).

## 5. Adding/removing keywords and sources

Unchanged from before - both live in `src/config.py`:

- **Keywords**: edit `HIGH_VALUE_KEYWORDS` / `MEDIUM_VALUE_KEYWORDS` /
  `LOW_VALUE_KEYWORDS` (case-insensitive, whole-word matching).
- **Sources**: edit the `ALLOWED_SOURCES` list - each entry has an `id`,
  `name`, `homepage`, optional `feed_candidates`, and a `scraper`.

After editing in GitHub, remember to **pull the change onto
PythonAnywhere and reload** - see [section 8](#8-updating-the-code-later).

## 6. Why PythonAnywhere instead of GitHub Actions

GitHub Actions is excellent for "run this on a timer," but it has no way
to listen for an incoming Telegram message in real time - it only wakes
up on a schedule you define, never in response to something happening
elsewhere. Making `/ognews` work requires something that's reachable by
Telegram at any moment: a webhook.

PythonAnywhere's free tier gives you one always-reachable web app with a
free HTTPS address and no credit card - a good fit since it costs
nothing and needs no code rewrite (it's still plain Python/Flask, reusing
every module already built). The one real trade-off: free-tier apps can
only make outbound requests to an allow-listed set of domains. If one of
your 6 sites ever returns nothing *specifically* on PythonAnywhere but
works everywhere else, that's almost certainly why - go to **Account →
Whitelisted websites** on PythonAnywhere and request it be added (it's a
quick, free approval for reasonable requests). Every other source keeps
working independently either way - one blocked domain never breaks the
rest.

## 7. How the ranking and cooldown work

**Ranking** (unchanged from the original design): every keyword has a
weight - high (3), medium (2), or low (1). A hit in the title counts
2.5x more than a hit only in the summary. A low-value keyword alone
(e.g. "free", "update", "launch") can never qualify an article by
itself - at least one high/medium match is required first. Articles
older than `LOOKBACK_HOURS` (in `src/config.py`, currently your 1-week
setting) are dropped rather than used as filler.

**Deduplication**: identical or near-identical URLs/titles are merged,
keeping whichever scored higher.

**Cooldown**: every successful `/ognews` reply records a timestamp in
`data/sent_history.json`. The next request checks how much time has
passed and refuses (politely) until 24 hours have elapsed. Change
`COOLDOWN_HOURS` in `src/config.py` if you want a different window.

## 8. Updating the code later

Because there's no more GitHub Actions auto-deploy, changes you make on
GitHub don't reach the live bot automatically anymore. After editing
anything in `src/config.py` (or any other file) on GitHub:

1. Open a **Bash console** on PythonAnywhere.
2. Run:
   ```
   cd YOUR_REPO_NAME
   git pull
   ```
3. Go to the **Web** tab and click **Reload**.

That's the whole update cycle - about 20 seconds of work each time.

## 9. Troubleshooting

**`/ognews` gets no reply at all**
- Confirm the webhook is actually registered: revisit the `setWebhook`
  URL from [section 3F](#f-tell-telegram-where-to-send-your-messages) -
  it should say `"ok":true`.
- On PythonAnywhere, **Web tab → Error log** - this shows Python
  exceptions from the app, including missing/incorrect credentials.
- Confirm you pressed **Start** on the bot at least once.
- Confirm the app is actually running: visit
  `https://YOUR_USERNAME.pythonanywhere.com/` directly - if that doesn't
  load, the deployment itself (not Telegram) is the problem.

**It replies "wait 24h" but you never got a first digest**
- That means `/ognews` genuinely ran once already (check
  `data/sent_history.json` via the **Files** tab for a
  `last_command_time` value) - possibly a duplicate Telegram delivery.
  Harmless; just wait out the cooldown or lower `COOLDOWN_HOURS`
  temporarily while testing.

**One specific source never contributes articles, only on PythonAnywhere**
- See the allow-list note in [section 6](#6-why-pythonanywhere-instead-of-github-actions).

**Credentials seem wrong**
- Re-open the WSGI configuration file (Web tab) and re-paste both values
  carefully, then Reload. Unlike GitHub Secrets, this file's contents
  *are* visible to you when you open it (only to you, since it's your
  private PythonAnywhere account) - useful for double-checking.

## 10. Known limitations

- **Free PythonAnywhere outbound requests are allow-listed** - see
  section 6. Doesn't crash anything; that source just contributes 0
  articles until whitelisted.
- **No more automatic daily send.** This is now purely on-demand - if
  you want a message every day without asking, that's a different design
  (the earlier scheduled version) and would need re-adding.
- **Cooldown is a simple 24-hour timer from your last successful use**,
  not tied to a calendar day - using it at 11 PM means your next use
  isn't available until 11 PM the next day, not just after midnight.
- **A slow reply (10-30 seconds) is normal** - it's genuinely fetching 6
  live websites in that time, not stuck.
- **Code changes require a manual `git pull` + Reload** on PythonAnywhere
  - see section 8.
