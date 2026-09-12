# Daily News Digest Telegram Bot

Sends you a Telegram message every day at 9:00 AM (your timezone) with up
to 25 of the most relevant news stories, pulled only from 6 sites you
chose, ranked by how well they match your interests. Costs $0/month to
run.

This guide assumes no programming experience. Follow it top to bottom.

---

## Contents

1. [How it works, in one page](#1-how-it-works-in-one-page)
2. [Why this architecture](#2-why-this-architecture)
3. [What's in this project](#3-whats-in-this-project)
4. [Setup: step by step](#4-setup-step-by-step)
5. [Entering your Telegram credentials](#5-entering-your-telegram-credentials)
6. [Setting your timezone](#6-setting-your-timezone)
7. [Testing before you trust it](#7-testing-before-you-trust-it)
8. [Adding or removing keywords](#8-adding-or-removing-keywords)
9. [Adding or removing news sources](#9-adding-or-removing-news-sources)
10. [How the ranking system works](#10-how-the-ranking-system-works)
11. [How duplicate detection works](#11-how-duplicate-detection-works)
12. [How the daily schedule works](#12-how-the-daily-schedule-works)
13. [Troubleshooting](#13-troubleshooting)
14. [Known limitations of the free setup](#14-known-limitations-of-the-free-setup)

---

## 1. How it works, in one page

Once a day, a small Python program:

1. Downloads the article list from each of your 6 sites (using RSS feeds
   where available, or reading the page directly where it isn't).
2. Throws out anything you've already been sent before.
3. Scores each remaining article against your keyword list, weighting
   specific/high-value keywords more than generic ones, and requiring at
   least one specific/meaningful keyword match before an article can
   qualify at all.
4. Removes near-duplicate stories, keeping the strongest version.
5. Takes the top 25 (or fewer, if fewer genuinely qualify).
6. Sends them to your Telegram chat as a clean numbered list.
7. Remembers what it sent, so tomorrow it won't repeat itself.

It runs on **GitHub Actions**, a free automation service, on a schedule -
there is no server for you to keep running, pay for, or maintain.

## 2. Why this architecture

You asked me to choose the technology, prioritizing **reliability, then
simplicity, then zero cost, then maintainability**. Here's the reasoning:

| Option considered | Verdict |
|---|---|
| **GitHub Actions (scheduled workflow)** | **Chosen.** Free and unlimited on public repos, no server to maintain, no "wake up a sleeping app" cold-start problem, built-in secret storage, built-in run logs for troubleshooting, and it can commit its own memory file back to the repo so history survives between runs. |
| PythonAnywhere free tier | Free tier scheduled tasks are limited (one task/day, fixed to a single time-of-day slot with no timezone control, and the account can be disabled after long inactivity). Less reliable and less flexible than Actions for this use case. |
| Render.com / Railway free cron | Free tiers on these platforms have changed frequently and often require a credit card or sleep after inactivity. Less predictable long-term than GitHub Actions, which has offered free CI/CD minutes on public repos for years. |
| AWS Lambda + EventBridge | Genuinely free-tier eligible, but requires an AWS account, IAM permissions, and more moving parts (a bundling/deployment step) than a single Python script - overkill for "don't overengineer." |
| A repl.it / always-on script on your own machine | Not reliable (depends on your computer being on) and not really "serverless." |

GitHub Actions won on every one of your four priorities at once, which is
why the rest of this project is built around it.

**Persistent storage** (remembering which articles were already sent)
uses a plain JSON file committed back into the repository after each
run - no database needed. This keeps the whole project to "a Python
script plus one config file plus one small data file," matching your
"don't overengineer" instruction.

**Scraping vs. RSS**: the bot tries each source's RSS/Atom feed first
(including auto-discovering one from the page's `<link rel="alternate">`
tag if you didn't hardcode it), and only falls back to reading the raw
page when no feed is available. Where I could confirm a source's actual
page structure, I wrote a scraper matched to that structure rather than
a one-size-fits-all scraper (see `src/fetchers.py`).

## 3. What's in this project

```
telegram-news-digest/
├── .github/workflows/daily-digest.yml   <- the schedule (GitHub Actions)
├── data/sent_history.json               <- the bot's memory (auto-updated)
├── src/
│   ├── main.py             <- entry point, orchestrates everything
│   ├── config.py            <- keywords, sources, all the settings you'll tweak
│   ├── fetchers.py           <- downloads articles (RSS + scrapers)
│   ├── scoring.py             <- relevance ranking
│   ├── dedup.py                <- duplicate detection
│   ├── telegram_sender.py       <- formats and sends the Telegram message
│   ├── storage.py                <- reads/writes the memory file
│   └── logging_setup.py           <- logging configuration
├── requirements.txt          <- the 3 Python packages it needs
├── .env.example                <- template for local testing only
└── README.md                     <- this file
```

## 4. Setup: step by step

### Step A - Create a GitHub account (skip if you have one)

Go to [github.com](https://github.com) and sign up. It's free.

### Step B - Create a new repository

1. Click the **+** icon (top right) → **New repository**.
2. Name it anything, e.g. `news-digest-bot`.
3. Leave it **Public**. (This makes GitHub Actions completely free and
   unlimited - see [section 14](#14-known-limitations-of-the-free-setup)
   for why this is safe even though your bot token stays private
   regardless.) If you'd strongly prefer Private, that also works, just
   note the Actions-minutes caveat later in this doc.
4. Click **Create repository**.

### Step C - Upload the project files

The most foolproof way to do this in a browser, with no command line:

1. On your new repo's page, click **Add file → Upload files**.
2. Open the project folder you downloaded on your computer, select
   **all files and folders inside it**, and drag them into the browser
   upload area. Modern browsers (Chrome, Edge) preserve the folder
   structure (`.github/`, `src/`, `data/`) when you drag a folder in.
3. Scroll down and click **Commit changes**.
4. Afterwards, open the repository's file list and confirm you can see
   the `.github`, `src`, and `data` folders, not just loose files. If the
   folder structure got flattened, delete what was uploaded and instead
   use **Add file → Create new file**, and for each file, type its full
   path (e.g. `src/main.py`) into the filename box - GitHub will create
   the folders automatically. This is slower but always works.

*(If you're comfortable with git/GitHub Desktop, you can of course just
`git push` the folder instead - same result.)*

### Step D - Add your secrets and settings

See [section 5](#5-entering-your-telegram-credentials) and
[section 6](#6-setting-your-timezone) below - do this before your first
real run.

### Step E - Confirm Actions is enabled

Go to the **Actions** tab of your repository. If you see a button to
enable workflows, click it. You should then see a workflow called
**Daily News Digest** listed.

That's it - the bot will now run automatically every hour and send your
digest during the hour you configured.

## 5. Entering your Telegram credentials

Your bot token and user ID are secrets. They are **never** put in the
code - they're stored using GitHub's encrypted Secrets feature, which
even you can't view again after saving (only the workflow can use them).

1. In your repository, go to **Settings** (top menu of the repo, not
   your account settings) → **Secrets and variables** → **Actions**.
2. Make sure you're on the **Secrets** tab.
3. Click **New repository secret**.
   - Name: `TELEGRAM_BOT_TOKEN`
   - Value: the token BotFather gave you (looks like
     `123456789:AAHk...`)
   - Click **Add secret**.
4. Click **New repository secret** again.
   - Name: `TELEGRAM_USER_ID`
   - Value: your numeric Telegram user ID
   - Click **Add secret**.

That's the exact place - `Settings → Secrets and variables → Actions →
Secrets tab → New repository secret` - for both `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_USER_ID`.

**One more Telegram-side step:** open a chat with your bot in the
Telegram app and send it any message (e.g. "hi"), or press **Start**.
Telegram bots cannot message a user who has never started a
conversation with them - this is a Telegram rule, not something the code
can work around.

## 6. Setting your timezone

Timezone and the send-hour are not secret, so they go in **Variables**,
right next to Secrets:

1. Same page as above: **Settings → Secrets and variables → Actions**.
2. Click the **Variables** tab this time (not Secrets).
3. Click **New repository variable**.
   - Name: `TIMEZONE`
   - Value: your IANA timezone name, e.g. `America/New_York`,
     `Europe/Riga`, `Europe/London`, `Asia/Tokyo`, `Australia/Sydney`.
     Full list:
     [Wikipedia - List of tz database time zones](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)
     (use the value in the "TZ identifier" column).
   - Click **Add variable**.
4. (Optional) Click **New repository variable** again if you want a time
   other than 9 AM:
   - Name: `DIGEST_HOUR`
   - Value: an hour from `0` to `23` (24-hour clock, local time). Leave
     this one out entirely to keep the default of `9`.

If you skip setting `TIMEZONE` altogether, the bot defaults to UTC -
it will still run, just not necessarily at 9 AM where you are, so it's
worth setting this.

Daylight saving time is handled automatically - see
[section 12](#12-how-the-daily-schedule-works).

## 7. Testing before you trust it

Don't wait until tomorrow's 9 AM to find out if it works. Run it by hand:

1. Go to the **Actions** tab → **Daily News Digest** (left sidebar) →
   **Run workflow** button (top right).
2. Tick **dry_run** the first time. This builds the whole digest and
   prints it to the log, but does **not** message you and does **not**
   mark anything as "sent" - completely safe to run as many times as
   you like while you're getting things right.
3. Click **Run workflow**, wait about 10-20 seconds, then click into the
   run and open the **Run digest bot** step to read the log. You'll see
   exactly which sources returned articles, how many were scored
   relevant, and the final ranked list with each story's score and which
   keywords matched it.
4. Once that looks right, run it again with **force_run** ticked instead
   (and dry_run off) to send yourself a real test digest immediately,
   regardless of the current time or whether one was already sent today.

## 8. Adding or removing keywords

Open `src/config.py` in GitHub (click the file, then the pencil/edit
icon) and find these three lists near the top:

```python
HIGH_VALUE_KEYWORDS = [
    "TikTok", "Instagram", ...
]
MEDIUM_VALUE_KEYWORDS = [
    "algorithm", "ranking", ...
]
LOW_VALUE_KEYWORDS = [
    "ban", "block", ...
]
```

- **To add a keyword:** add it as a new quoted string in whichever list
  matches how specific/important it is, e.g.
  `HIGH_VALUE_KEYWORDS = [..., "Midjourney"]`.
- **To remove one:** delete its entry from the list.
- Matching is always case-insensitive and works on whole
  words/phrases (so `"voice-clone"` won't accidentally match inside an
  unrelated longer word).
- Multi-word keywords like `"Nano Banana"` work fine as-is.

Scroll to the bottom of the file and click **Commit changes**. No other
file needs to change - keywords take effect on the very next run.

## 9. Adding or removing news sources

Also in `src/config.py`, find `ALLOWED_SOURCES` near the top. Each source
looks like this:

```python
{
    "id": "martech",
    "name": "MarTech",
    "homepage": "https://martech.org/",
    "feed_candidates": ["https://martech.org/feed/"],
    "scraper": "scrape_generic",
},
```

- **To remove a source:** delete its whole `{...}` block.
- **To add a source:** copy an existing block, give it a unique `id`,
  the display `name` you want shown in Telegram, its `homepage`, and any
  RSS feed URL you know of in `feed_candidates` (or leave that list
  empty - `[]` - if you don't know one). Set `"scraper": "scrape_generic"`
  unless you're comfortable writing a custom parser function in
  `src/fetchers.py` for a site with an unusual layout.

The bot always tries RSS first and only scrapes the page directly if no
feed works, so adding a source with just a homepage and an empty
`feed_candidates` list will usually still work fine via automatic feed
discovery or the generic scraper.

## 10. How the ranking system works

Every keyword has a weight:

| Tier | Weight | Examples |
|---|---|---|
| High | 3 | TikTok, Instagram, Sora, Shopify, shadowban, GEO, deminimis |
| Medium | 2 | algorithm, SEO, ecommerce, tariff, deepfake, ROAS |
| Low | 1 | free, update, launch, policy, sale, block |

For each article:

- A keyword match **in the title** counts 2.5x more than a match only in
  the summary/snippet, since the title is the best signal of what the
  story is actually about.
- **A low-value keyword can never qualify an article by itself.** An
  article needs at least one *high* or *medium* match somewhere before
  it's considered at all - this is what stops something like "free
  update" on an unrelated topic from ranking highly, per your
  requirement.
- Once an article qualifies, every additional keyword match (including
  low-value ones) adds to its score, so an article that's clearly about
  several of your interests at once outranks one that just barely
  qualifies.
- A **recency bonus** (worth up to 3 points) is added for articles
  published in the last 48 hours, fading to zero by the 48-hour mark.
  Articles older than 48 hours (when a publish date is available) are
  dropped entirely rather than used as filler.

This is a transparent, rule-based system, not an AI model reading each
article - it's designed to be predictable and free to run. It will
occasionally miss nuance a human editor wouldn't (see
[Known limitations](#14-known-limitations-of-the-free-setup)); if you
find it's consistently over- or under-including a topic, that's a sign
to adjust that keyword's tier in `config.py`.

## 11. How duplicate detection works

- Two articles with the same URL (ignoring `http` vs `https`, trailing
  slashes, and tracking parameters) are always treated as one.
- Two articles with very similar titles (compared with a standard
  text-similarity algorithm, not just exact matches) are also treated as
  duplicates.
- When a duplicate is found, the bot keeps whichever version it already
  ranked higher (it sorts by score first, then removes duplicates), so
  you get the strongest write-up of a story, not just the first one it
  happened to see.
- This is title-based, not full-article-based, so two very differently
  *worded* headlines about the same underlying event (e.g. two outlets
  covering a TikTok bill with different angles) may both appear - that's
  intentional, since different angles are often genuinely useful, and
  matches your instruction to keep both when the coverage adds distinct
  value.

## 12. How the daily schedule works

GitHub Actions' scheduler only understands UTC, and a fixed UTC time
would silently drift by an hour every spring/fall when your local
timezone's daylight saving changes - a common failure mode for "free"
scheduled bots.

To avoid that, the workflow runs **every hour**, and the Python script
itself checks the current local time in your configured `TIMEZONE` and
only proceeds past a quick check when it's actually your chosen
`DIGEST_HOUR`. Every other hourly trigger exits almost instantly without
fetching anything. This means:

- 9:00 AM is always 9:00 AM in *your* timezone, automatically, through
  DST changes, with no manual updates ever needed.
- A run also checks "did I already send today's digest?" before doing
  anything else, so even if GitHub's scheduler happens to fire twice
  near the boundary, you won't get two digests.
- GitHub doesn't guarantee scheduled workflows fire at the exact minute
  requested (it can be a few minutes late under load) - because this
  design checks "is it the right *hour*," not "is it exactly 9:00:00,"
  a busy scheduler still won't cause you to miss a whole day.

## 13. Troubleshooting

**I'm not receiving any messages at all**
- Confirm you pressed **Start** (or sent any message) to your bot in
  Telegram - bots can't message you first otherwise.
- Double-check `TELEGRAM_BOT_TOKEN` and `TELEGRAM_USER_ID` are spelled
  exactly like that (case-sensitive) under **Settings → Secrets and
  variables → Actions → Secrets**, with no extra spaces.
- Go to the **Actions** tab and open the most recent **Daily News
  Digest** run. Open the **Run digest bot** step and read the log - it
  will tell you plainly if credentials are missing or if Telegram
  rejected the message (and why).

**The workflow doesn't seem to run at all**
- Check the **Actions** tab is enabled (see [Step E](#step-e---confirm-actions-is-enabled)).
- GitHub automatically pauses scheduled workflows on repositories with
  no activity for 60 days. Because a successful run commits an update
  to `data/sent_history.json` roughly once a day, this shouldn't happen
  on its own - but if you ever see the schedule has stopped, go to
  **Actions → Daily News Digest** and click **Enable workflow**.

**A specific source never contributes any articles**
- Open a recent run's log and search for that source's `id`. You'll see
  either "RSS feed OK" or "falling back to scraping," and a count of
  articles found. If a source consistently returns 0, its page layout
  likely changed. It won't break the other 5 sources - each one fails
  independently - but you may want to check whether its RSS feed URL in
  `src/config.py` still resolves, or update the scraper.

**I'm getting way too many / too few stories, or the wrong topics**
- Use `dry_run` (see [section 7](#7-testing-before-you-trust-it)) and
  read the per-article score + matched-keywords log line for a few runs.
  Then tune the keyword tiers as described in
  [section 8](#8-adding-or-removing-keywords).

**Telegram says "chat not found" or similar**
- This almost always means `TELEGRAM_USER_ID` is wrong, or you haven't
  started a chat with the bot yet.

## 14. Known limitations of the free setup

- **Public repository = unlimited free Actions minutes.** Private
  repositories get 2,000 free minutes/month on GitHub's free plan.
  Running hourly uses roughly 500-800 minutes/month depending on how
  long each run takes, which fits, but leaves less room for anything
  else you might add later. If in doubt, keep the repo public - your
  bot token and user ID stay encrypted and hidden either way; making the
  repo public only exposes the *code*, not your secrets.
- **This is a scheduled batch job, not an always-on server.** It can
  only *send* you messages on schedule; it can't listen for or respond
  to messages you send the bot (that would need a different, always-on
  design, which isn't free to host reliably).
- **Scraping fallbacks are inherently less stable than RSS.** Sites that
  don't offer RSS may occasionally change their page layout in a way
  that breaks that one source's scraper. The bot is built to fail
  gracefully (log it, skip that source, keep going) rather than crash,
  but you may occasionally need to glance at the logs and nudge a
  scraper back into shape.
- **Ranking is a rules-based heuristic, not an AI reading the article.**
  It's deliberately transparent and free to run, but it can occasionally
  misjudge context in ways a human (or a paid AI service) wouldn't. Tune
  keyword tiers over time if you notice a pattern.
- **GitHub's scheduler is "best effort" on timing** - typically within a
  few minutes of the hour, occasionally more under heavy load. The
  hourly-check design (section 12) absorbs this without causing missed
  or duplicate digests.
- **A few of your keywords are short, common acronyms** (e.g. `GEO`)
  that can occasionally appear in unrelated contexts even with
  whole-word matching. Because low-value/ambiguous hits alone can't
  qualify an article, this is unlikely to cause false positives on its
  own, but it's worth knowing about if you ever see a surprising story
  in your digest.
