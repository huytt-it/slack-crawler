# SlackCrawler — Internal Slack Incremental Sync

A CLI tool that pulls message history from Slack channels incrementally and persists the data for downstream analytics or RAG pipelines.

**Internal use only.** This tool is designed for internally built Slack apps — not for distribution on the Slack Marketplace. Data retrieved is for RAG/inference purposes, not for LLM training or fine-tuning.

---

## 1. Create the Internal Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**.
2. Name it (e.g. "Data Sync") and select your workspace.
3. Go to **OAuth & Permissions** → **User Token Scopes** and add:

| Scope | Purpose |
|---|---|
| `channels:history` | Read messages in public channels |
| `channels:read` | List public channels |
| `groups:history` | Read messages in private channels |
| `groups:read` | List private channels |
| `users:read` | Resolve user IDs to names |
| `users:read.email` | Resolve user emails (optional, for pseudonymization) |
| `files:read` | Download file attachments (required if using `--download-files`) |

> **Optional DM scopes:** Add `im:history` and `mpim:history` if you need to pull direct messages. You will also need to add `im` and `mpim` to the `types` parameter in `channels.py`.

4. **Install to Workspace** and copy the **User OAuth Token** (`xoxp-...`).

> A **Bot Token** (`xoxb-...`) also works but will only see channels the bot has been invited to. User tokens see all channels the installing user is a member of.

---

## 2. Configuration

Configuration is loaded from environment variables and/or a YAML config file. Env vars take precedence.

Copy the example config:

```bash
cp config.example.yaml config.yaml
```

### Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SLACK_TOKEN` | **Yes** | — | `xoxp-...` or `xoxb-...` token |
| `OUTPUT_MODE` | No | `ndjson` | `ndjson` or `postgres` |
| `DB_CONNECTION_STRING` | If postgres | — | PostgreSQL connection string |
| `OUTPUT_DIR` | No | `output` | Directory for NDJSON files |
| `STATE_DIR` | No | `.state` | Directory for watermark state |
| `CHANNEL_ALLOWLIST` | No | — | Comma-separated channel IDs or names |
| `CHANNEL_DENYLIST` | No | — | Comma-separated channel IDs or names |
| `LOOKBACK_DAYS` | No | `90` | First-run lookback window (days) |
| `PAGE_SIZE` | No | `200` | Page size for conversations.history |
| `THREAD_PAGE_SIZE` | No | `200` | Page size for conversations.replies |
| `MAX_RETRIES` | No | `5` | Max retries on transient errors / 429 |
| `PSEUDONYMIZE` | No | `false` | Replace user names with hashed IDs |
| `DOWNLOAD_FILES` | No | `false` | Download file attachments to `output/<channel>/files/` |
| `SYNC_SINCE` | No | — | Start date `YYYY-MM-DD` (overrides watermark & lookback) |
| `SYNC_UNTIL` | No | — | End date `YYYY-MM-DD` (only fetch messages before this) |

---

## 3. Install & Run

```bash
# Create a virtualenv
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Set the token
export SLACK_TOKEN="xoxp-your-token"

# Run
python main.py

# With verbose logging
python main.py -v

# With a specific config file
python main.py -c /path/to/config.yaml

# Export a specific date range
python main.py --since 2025-01-01 --until 2025-06-30

# Export everything from a specific date to now
python main.py --since 2025-03-01

# Download file attachments
python main.py --download-files
```

> **Note:** `--since` overrides both the watermark and `LOOKBACK_DAYS`. Without `--since`, the tool runs incrementally from the last watermark as usual.

### Quick run with a batch file (Windows)

Create a file called `run.bat`, paste the template below, fill in your token, and double-click to run.
`run.bat` is gitignored so your token stays safe.

```bat
@echo off
setlocal

:: ===================
::  REQUIRED
:: ===================
set SLACK_TOKEN=xoxp-your-token-here

:: ===================
::  OUTPUT
:: ===================
:: ndjson (default) or postgres
set OUTPUT_MODE=ndjson

:: Directory for output files (default: output)
set OUTPUT_DIR=output

:: Postgres connection string (required if OUTPUT_MODE=postgres)
:: set DB_CONNECTION_STRING=postgresql://user:pass@localhost:5432/slack_data

:: ===================
::  CHANNEL FILTER
:: ===================
:: Only sync these channels (comma-separated names or IDs, empty = all)
:: set CHANNEL_ALLOWLIST=general,engineering

:: Exclude these channels
:: set CHANNEL_DENYLIST=random,social

:: ===================
::  SYNC OPTIONS
:: ===================
:: How many days back on the first run (default: 90)
set LOOKBACK_DAYS=90

:: Download file attachments to output/<channel>/files/
:: set DOWNLOAD_FILES=true

:: Incremental sync: true = only fetch new messages, false = re-fetch from lookback_days
:: set USE_WATERMARK=true

:: Replace user names with hashed IDs
:: set PSEUDONYMIZE=true

:: ===================
::  ADVANCED
:: ===================
:: Messages per API call (default: 200)
:: set PAGE_SIZE=200

:: Replies per API call (default: 200)
:: set THREAD_PAGE_SIZE=200

:: Max retry attempts on errors (default: 5)
:: set MAX_RETRIES=5

:: ===================
::  RUN
:: ===================
python main.py -v %*

endlocal
pause
```

> **Usage:** `run.bat`, `run.bat --since 2025-01-01`, `run.bat --download-files`, etc. Any CLI flags are passed through via `%*`.
> To enable an option, remove `:: ` at the start of the line. To disable, add `:: ` back.

### Channel filtering

By default the tool syncs **all channels you have joined** (public + private). Use allowlist/denylist to control which channels are synced.

You can use **channel names** or **channel IDs** (e.g. `C01ABCDEF12`).
To find a channel ID: right-click the channel in Slack → **View channel details** → scroll to the bottom.

#### Sync only specific channels (allowlist)

```bat
:: run.bat
set CHANNEL_ALLOWLIST=general,engineering,C01ABCDEF12
```

```yaml
# config.yaml
channel_allowlist:
  - general
  - engineering
  - C01ABCDEF12
```

#### Exclude specific channels (denylist)

```bat
:: run.bat
set CHANNEL_DENYLIST=random,social
```

```yaml
# config.yaml
channel_denylist:
  - random
  - social
```

#### Combine allowlist + denylist

```bat
set CHANNEL_ALLOWLIST=general,engineering,random
set CHANNEL_DENYLIST=random
```

Result: syncs `general` and `engineering` only. Allowlist is applied first, then denylist removes matches.

#### Summary

| Config | Behavior |
|---|---|
| Both empty (default) | Sync all channels you are a member of |
| Allowlist only | Sync only listed channels |
| Denylist only | Sync all channels except listed ones |
| Both set | Allowlist first, then denylist removes from that set |

### Postgres mode

```bash
export SLACK_TOKEN="xoxp-..."
export OUTPUT_MODE="postgres"
export DB_CONNECTION_STRING="postgresql://user:pass@localhost:5432/slack_data"
python main.py
```

The tool auto-creates the required tables (`slack_messages`, `slack_users`, `slack_watermarks`) on first run. Messages are upserted on `(channel_id, ts)` so re-runs are idempotent.

---

## 4. Scheduling

This tool is a **one-shot CLI** — run it via any scheduler.

### cron (Linux/macOS)

```bash
# Daily at 2 AM
0 2 * * * cd /path/to/SlackCrawler && .venv/bin/python main.py >> /var/log/slack-sync.log 2>&1

# Weekly on Sunday at midnight
0 0 * * 0 cd /path/to/SlackCrawler && .venv/bin/python main.py

# Monthly on the 1st at 3 AM
0 3 1 * * cd /path/to/SlackCrawler && .venv/bin/python main.py
```

### GitHub Actions

```yaml
name: Slack Sync
on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM UTC
  workflow_dispatch:       # Manual trigger

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python main.py
        env:
          SLACK_TOKEN: ${{ secrets.SLACK_TOKEN }}
```

> **Note:** For GitHub Actions, persist the `.state/` directory between runs (e.g. commit it, use a cache action, or use an external store like S3/Postgres for watermarks).

### Azure Functions Timer

Create a timer-triggered Azure Function that invokes `main.py`. Set `SLACK_TOKEN` in the Function App's Application Settings.

### Windows Task Scheduler

```
Program: C:\path\to\.venv\Scripts\python.exe
Arguments: C:\path\to\SlackCrawler\main.py
Start in: C:\path\to\SlackCrawler
```

---

## 5. How It Works

1. **Channel discovery** — calls `users.conversations` to list channels the token owner is a member of. Filters by allowlist/denylist.
2. **User resolution** — calls `users.list` once per run, caches the mapping.
3. **Incremental sync** — for each channel, reads the stored watermark (the `ts` of the last synced message). Fetches only messages with `ts > watermark` using the `oldest` parameter.
4. **Thread fetch** — for any message with `reply_count > 0`, fetches the full thread via `conversations.replies`.
5. **File download** (optional) — if `--download-files` is set, downloads attachments to `output/<channel>/files/`.
6. **Persist** — writes normalized messages to NDJSON files or Postgres.
7. **Advance watermark** — only after a channel completes successfully, so a crash mid-run won't skip messages on the next run.

### Rate limits

This is an internal app, so it uses normal Slack API rate limits (not the reduced limits for unlisted Marketplace apps). The tool handles HTTP 429 responses by reading the `Retry-After` header and sleeping accordingly. Transient errors get exponential backoff.

---

## 6. Output Structure

```
output/
├── general/
│   ├── messages.ndjson
│   └── files/                  # only when --download-files is enabled
│       ├── F07ABC_report.pdf
│       └── F07DEF_screenshot.png
├── engineering/
│   ├── messages.ndjson
│   └── files/
└── _users.json
```

Each channel gets its own directory. Messages are in `messages.ndjson`, file attachments (if enabled) are in `files/`.

### Message Schema

Each line in `messages.ndjson` is a JSON object:

| Field | Type | Description |
|---|---|---|
| `channel_id` | string | Slack channel ID |
| `channel_name` | string | Human-readable channel name |
| `ts` | string | Message timestamp (Slack's unique ID) |
| `datetime_utc` | string | ISO 8601 UTC timestamp |
| `user_id` | string | Author's Slack user ID |
| `thread_ts` | string | Parent thread timestamp (null if top-level) |
| `text` | string | Message text |
| `type` | string | Message type |
| `subtype` | string | Message subtype (null for normal messages) |
| `reactions` | json | Reaction data (null if none) |
| `reply_count` | int | Number of thread replies |
| `raw` | json | Original Slack API response |
| `downloaded_files` | json / absent | List of downloaded files (only present when `--download-files` is used and message has attachments) |

---

## 7. Assumptions & Design Decisions

- **Date range export:** use `--since` and `--until` (or `SYNC_SINCE` / `SYNC_UNTIL` env vars) to export a specific date range. `--since` overrides the watermark and lookback, so the tool always starts from the date you specify.
- **First-run lookback** defaults to 90 days. Set `LOOKBACK_DAYS` to adjust.
- **Deleted messages** are not captured retroactively — Slack's `conversations.history` only returns non-deleted messages within the workspace's retention window.
- **Bot messages** are included (they have `user_id` set to the bot's ID or `bot_id`).
- **Pseudonymization** is opt-in. When enabled, user display names and real names are replaced with a stable SHA-256 hash prefix of their email (or user ID if no email).
- **Watermarks use Slack's `ts`** (a string like `"1234567890.123456"`), which is both a timestamp and a unique message ID.
- The NDJSON backend appends to files, making it safe for incremental runs. To rebuild from scratch, delete the `output/` and `.state/` directories.
