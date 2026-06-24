# SlackCrawler — Architecture

> Internal Slack data sync tool. Pulls message history (public + private channels),
> threads, users, and file attachments incrementally and persists them as files
> (NDJSON) for downstream analytics / RAG. One-shot CLI, scheduler-driven.

---

## 1. System Overview

SlackCrawler is a **stateless, one-shot batch CLI**. Each invocation:

1. Discovers the channels the token's identity belongs to.
2. Resolves the user directory once.
3. Streams each channel's new messages (since a per-channel watermark), page by page.
4. Fetches threads and (optionally) downloads file attachments.
5. Writes everything to per-channel NDJSON files and checkpoints progress after every page.

It is designed to be invoked by an external scheduler (cron / GitHub Actions /
Azure Functions Timer / Windows Task Scheduler). There is **no internal daemon**.

```
                          ┌────────────────────────────────────────────┐
                          │                 main.run()                    │
                          │   orchestration · ThreadPool · dry-run        │
                          └───────────────┬──────────────────────────────┘
                                          │
        ┌─────────────────┬──────────────┼───────────────┬─────────────────┐
        ▼                 ▼              ▼                ▼                 ▼
 ┌─────────────┐  ┌──────────────┐ ┌───────────┐  ┌─────────────┐  ┌─────────────┐
 │  channels   │  │    users     │ │  probe    │  │   history   │  │   threads   │
 │ discovery   │  │  resolver    │ │ estimate  │  │  (stream)   │  │  (replies)  │
 └──────┬──────┘  └──────┬───────┘ └─────┬─────┘  └──────┬──────┘  └──────┬──────┘
        │                │               │               │                │
        └────────────────┴───────────────┴───────────────┴────────────────┘
                                          │ every API call
                                          ▼
                          ┌──────────────────────────────────┐
                          │  SlackClient  (retry · 429 · jitter)│
                          │  RateLimiter  (shared token bucket) │
                          └──────────────────┬─────────────────┘
                                             ▼
                                    Slack Web API (slack_sdk)

        per page ▼ write + checkpoint                    optional ▼
 ┌──────────────────────────┐                     ┌──────────────────────────┐
 │   StorageBackend         │                     │   FileDownloader         │
 │   NdjsonBackend (default)│                     │   (parallel · Session)   │
 │   PostgresBackend (opt)  │                     │   files/ + _files_index  │
 └────────────┬─────────────┘                     └────────────┬─────────────┘
              ▼                                                  ▼
   output/<channel>/messages.ndjson                  output/<channel>/files/*
   output/<channel>/raw.ndjson                       output/<channel>/_files_index.json
   .state/watermarks.json  (per-page checkpoint)
```

---

## 2. Folder & File Structure

### Source layout

```
SlackCrawler/
├── main.py                       # CLI entry point + run orchestration (ThreadPool, dry-run)
├── requirements.txt              # slack_sdk, pyyaml, psycopg2-binary, requests
├── config.example.yaml           # template config (copy to config.yaml)
├── run.example.bat               # Windows one-click run template (copy to run.bat)
├── README.md                     # user guide (setup, scopes, usage, scheduling)
├── ARCHITECTURE.md               # this document
├── .gitignore                    # excludes .env, run.bat, output/, .state/, .claude/
│
├── slack_sync/                   # package
│   ├── __init__.py
│   ├── config.py                 # Config dataclass + env/YAML loader (env > YAML > default)
│   ├── client.py                 # SlackClient: API wrapper, 429 + transient retry, jitter
│   ├── ratelimit.py              # RateLimiter: thread-safe token bucket (shared budget)
│   ├── channels.py               # discover_channels + allowlist/denylist filtering
│   ├── users.py                  # UserResolver: users.list cache + pseudonymization hook
│   ├── state.py                  # WatermarkStore: per-page checkpoint + resumable descent
│   ├── history.py                # iter_channel_history (streaming) + normalize_message
│   ├── threads.py                # fetch_thread_replies (paginated, parent-skipped)
│   ├── files.py                  # FileDownloader: parallel download, Session, file index
│   ├── probe.py                  # one-page estimate + dry-run report
│   └── storage/
│       ├── __init__.py           # StorageBackend ABC (pluggable interface)
│       ├── ndjson.py             # NdjsonBackend (default) — per-channel dirs, raw split
│       └── postgres.py           # PostgresBackend (optional) — idempotent upsert
│
└── tests/                        # 71 tests (pytest)
    ├── test_config.py            # config validation, env/YAML precedence
    ├── test_channels.py          # discovery + allow/deny filtering
    ├── test_history.py           # normalization, streaming pagination
    ├── test_threads.py           # reply fetch, parent skip, pagination
    ├── test_state.py             # watermark, migration, checkpoint/resume lifecycle
    ├── test_storage_ndjson.py    # raw split, append, per-channel dirs
    ├── test_users.py             # resolution, caching, pseudonymization
    ├── test_files.py             # download, size cap, dedup, file index
    ├── test_ratelimit.py         # token-bucket burst + throttle
    ├── test_probe.py             # estimate extrapolation, file sizing
    └── test_main.py              # date→ts helper
```

### Output layout (runtime, gitignored)

```
output/
├── general/
│   ├── messages.ndjson           # normalized fields, one JSON per line (lean, for RAG)
│   ├── raw.ndjson                # original Slack payloads (keyed by channel_id+ts) — optional
│   ├── _files_index.json         # downloaded-file metadata (sender, datetime, thread, size)
│   └── files/                    # downloaded attachments: <file_id>_<original_name>
│       ├── F07ABC_report.pdf
│       └── F07DEF_diagram.png
├── engineering/
│   └── messages.ndjson
└── _users.json                   # user_id → {display_name, real_name, email}

.state/
└── watermarks.json               # per-channel watermark + in-flight checkpoint
```

---

## 3. Component Reference

| Module | Responsibility | Key design notes |
|---|---|---|
| `main.py` | Orchestrates the run: discovery → users → per-channel parallel sync; handles `--dry-run`, CLI flag overrides, summary. | `ThreadPoolExecutor(MAX_WORKERS)`; per-channel errors are isolated (logged, others continue). |
| `config.py` | Immutable `Config` dataclass; merges env vars > YAML > defaults; validates. | Date format + output-mode + postgres-connection validation at construction. |
| `client.py` | Wraps `slack_sdk.WebClient`. Retries 429 (Retry-After + jitter) and Slack transient errors up to `max_retries`. | Acquires a `RateLimiter` token before each call. Thread-safe (stateless per call). |
| `ratelimit.py` | `RateLimiter` token bucket + `PerMethodRateLimiter` (one bucket per Slack method) so each method runs at its own tier. | History and replies have separate Slack buckets → fetched in parallel, not shared. |
| `channels.py` | `users.conversations` discovery for the configured `channel_types`, then allow/deny filtering by name or ID. | Cursor-paginated; degrades to public_channel (with a warning) if the token lacks private scope — no crash. |
| `users.py` | `users.list` cached once per run; maps id → names/email. Optional pseudonymization (stable SHA-256 of email). | Cache loaded lazily; pseudonymization is a clean hook. |
| `state.py` | Per-channel watermark + in-flight descent checkpoint. Thread-safe; atomic writes (tmp+rename). | `plan_run` / `checkpoint` / `complete`; migrates old flat format. |
| `history.py` | `iter_channel_history` **streams** pages (generator) so memory is bounded; `normalize_message` maps to schema. | `fetch_channel_history` wrapper kept for ad-hoc/test use. |
| `threads.py` | `conversations.replies` per thread; skips the parent (it already comes from history). | Paginated; incremental-aware via `oldest`. |
| `files.py` | Parallel attachment download (per-page pool), thread-local `requests.Session` (keep-alive), size cap, redirect-with-auth handling, file index. | Atomic temp+rename; dedup by file_id; index flushed per channel. |
| `probe.py` | One-page-per-channel estimate; `--dry-run` report (messages, pages, ETA, files, disk check). | Order-of-magnitude (time-density extrapolation); file sizes exact. |
| `storage/__init__.py` | `StorageBackend` ABC: `store_messages`, `store_users`, `close`. | Backends are pluggable behind this interface. |
| `storage/ndjson.py` | Default backend. Per-channel dirs; splits `raw` into `raw.ndjson`. | Append-friendly; safe for incremental runs. |
| `storage/postgres.py` | Optional backend. Auto-creates schema; idempotent upsert on `(channel_id, ts)`. | Not on the optimized file path; kept for parity. |

---

## 4. Data Flow (one run)

```
discover_channels ──► UserResolver.get_all ──► store_users
        │
        └──► ThreadPool(MAX_WORKERS): for each channel ─────────────────────────┐
                                                                                 │
   sync_channel(channel):                                                        │
     plan = WatermarkStore.plan_run(...)        # resolve [oldest,latest], resume?│
     for page in iter_channel_history(...):      # STREAM newest→oldest           │
         for msg with replies: fetch_thread_replies(...)                          │
         if download_files: FileDownloader.process_page_files(page)  # parallel   │
         storage.store_messages(page + replies) # append messages.ndjson/raw.ndjson│
         WatermarkStore.checkpoint(low=page_min, high=max_seen)   # PER PAGE      │
     WatermarkStore.complete(high)               # advance watermark, clear progress│
                                                                                 │
   ◄─────────────────────────────────────────────────────────────────────────── ┘
   FileDownloader.save_file_indexes() ──► summary log
```

---

## 5. Reliability — Retry & Resume (4 layers)

| Layer | Scope | Behavior | Limit |
|---|---|---|---|
| 1. slack_sdk built-in | per API call | Retries `URLError`/socket-timeout, `ConnectionReset`, `RemoteDisconnected` | **1 retry** (default) |
| 2. `SlackClient.api_call` | per API call | Retries HTTP 429 (Retry-After + jitter) and Slack transient errors | up to `max_retries` (5) |
| 3. Channel task | per channel | A channel that still fails is logged and **skipped**; other channels continue | no in-process channel restart |
| 4. Per-page checkpoint | across runs | Next invocation **resumes from the last completed page** (`.state`), re-fetching only the boundary page | requires re-running the tool |

**Guarantee:** a crash, kill, or power loss mid-channel never loses committed
progress — the next run continues the descent. Writes are atomic (temp+rename for
state and for downloaded files). Watermark advances **only** when a channel's full
descent completes.

**Caveat (at-least-once):** because NDJSON appends (no upsert), resuming may
re-append the single boundary page → rare duplicate lines at checkpoint
boundaries. Deduplicate downstream on `(channel_id, ts)` if exactness is required.

---

## 6. Non-Functional Characteristics

### Availability
- No long-running service to keep up; availability = scheduler uptime + resumable runs.
- Idempotent: safe to re-run anytime; resumes in-flight work and skips already-synced messages (watermark).
- Single point of dependency: the Slack API and one token (no horizontal token sharding yet).

### Usability
- Config via **env vars / YAML / CLI flags** with clear precedence (CLI > env > YAML > default).
- Sensible defaults; only `SLACK_TOKEN` is mandatory.
- `run.example.bat` one-click template (Windows); README template for `run.bat`.
- `--dry-run` to estimate size/disk/ETA before committing to a big pull.
- Structured `logging` (not print); token never logged (redacted by slack_sdk).

### Reliability
- 4-layer retry/resume (section 5); atomic writes; checkpointing.
- Per-channel error isolation — one bad channel doesn't abort the run.

### Scalability
- **Memory-bounded** by streaming: peak ≈ one page per worker, independent of channel size.
- **Parallel** across channels and file downloads; per-method rate limiters run history + replies buckets concurrently.
- **Throughput ceiling** = Slack's per-method rate limit. The two main levers are `PAGE_SIZE` (up to 1000 → ~5× fewer requests) and the per-method limiter; channel parallelism overlaps different work types but cannot exceed the per-method history rate for one token.

### Security
- Token read from env / secret manager; never hardcoded, never logged.
- `.gitignore` excludes `.env`, `run.bat`, `output/`, `.state/`, `.claude/`.
- Pseudonymization hook (stable hash) for privacy-preserving exports.
- Compliant scope: data for RAG/inference, not LLM training; internal app only.

### Maintainability
- Modular, single-responsibility files; full type hints + docstrings.
- Pluggable storage interface (add a backend by implementing 3 methods).
- 71 automated tests covering config, discovery, history, threads, state lifecycle, storage, users, files, rate limiter, probe.

---

## 7. Realistic Performance Estimates

> Assumptions: `page_size=1000` (default), `api_rate_per_sec=1.0` per method,
> internal app on normal Slack tiers. Message ≈ 0.5–1 KB normalized, 2–5 KB raw.
> Numbers are order-of-magnitude — real throughput is dominated by Slack rate
> limits and network.

### History throughput (API-bound)

| Total messages | History pages (÷1000) | Time @ 1 req/s | Time @ 3 req/s |
|---|---|---|---|
| 10,000 | 10 | ~10 s | ~3 s |
| 100,000 | 100 | ~1.7 min | ~33 s |
| 1,000,000 | 1,000 | ~17 min | ~6 min |
| 5,000,000 | 5,000 | ~83 min | ~28 min |

> `PAGE_SIZE=1000` makes ~5× fewer requests than 200 for the same data — the
> single biggest throughput lever. Threads add ~1 `conversations.replies` call per
> thread that has replies, but those draw from a **separate** Slack bucket (the
> per-method limiter), so they don't slow history. Raise `api_rate_per_sec` only
> within your Slack tier.

### Memory (bounded by streaming)

| Component | Footprint |
|---|---|
| Per worker (1 page + its threads in flight) | ~1–5 MB |
| User cache (`users.list`) | ~50 MB for 100k users (typically far less) |
| `_downloaded` file-id set | ~12 B × file count (~12 MB for 1M files) |
| File index (flushed per channel) | bounded to one channel's files |
| **Typical peak (4 workers)** | **well under ~300 MB regardless of channel size** |

### Disk (file backend)

| Item | Per 1M messages |
|---|---|
| `messages.ndjson` (lean) | ~0.5–1 GB |
| `raw.ndjson` (optional, `STORE_RAW`) | ~2–5 GB |
| Attachments | actual Slack file sizes (use `--dry-run` to size exactly) |

### File downloads (network-bound, parallel)

| Files / size | `FILE_WORKERS=4`, ~10 MB/s aggregate |
|---|---|
| 1,000 files / 5 GB | ~8–10 min |
| 10,000 files / 84 GB | ~2.5–3 hours |

> `--dry-run` reports exact estimated file bytes vs free disk before you commit.

---

## 8. Configuration Reference

| Key (env / YAML) | Default | Purpose |
|---|---|---|
| `SLACK_TOKEN` | *(required)* | User (`xoxp`) or bot (`xoxb`) token |
| `OUTPUT_MODE` / `output_mode` | `ndjson` | `ndjson` or `postgres` |
| `DB_CONNECTION_STRING` | — | required for postgres |
| `OUTPUT_DIR` / `output_dir` | `output` | output root |
| `STATE_DIR` / `state_dir` | `.state` | checkpoint/watermark dir |
| `CHANNEL_ALLOWLIST` / `channel_allowlist` | — | only these channels (name or id) |
| `CHANNEL_DENYLIST` / `channel_denylist` | — | exclude these channels |
| `CHANNEL_TYPES` / `channel_types` | `public_channel` | types to sync: `public_channel,private_channel,mpim,im` |
| `LOOKBACK_DAYS` / `lookback_days` | `90` | first-run history window |
| `PAGE_SIZE` / `page_size` | `1000` | conversations.history page size (max 1000) |
| `THREAD_PAGE_SIZE` / `thread_page_size` | `1000` | conversations.replies page size |
| `MAX_RETRIES` / `max_retries` | `5` | app-level retry attempts |
| `PSEUDONYMIZE` / `pseudonymize` | `false` | hash user names |
| `DOWNLOAD_FILES` / `download_files` | `false` | download attachments |
| `USE_WATERMARK` / `use_watermark` | `true` | incremental vs full re-fetch |
| `STORE_RAW` / `store_raw` | `true` | write `raw.ndjson` |
| `MAX_WORKERS` / `max_workers` | `4` | channels in parallel |
| `FILE_WORKERS` / `file_workers` | `4` | files in parallel |
| `MAX_FILE_SIZE_MB` / `max_file_size_mb` | `0` | skip files larger than (0 = no limit) |
| `API_RATE_PER_SEC` / `api_rate_per_sec` | `1.0` | per-method API request budget (each Slack method gets its own bucket) |
| `SYNC_SINCE` / `since` | — | start date `YYYY-MM-DD` (CLI `--since`) |
| `SYNC_UNTIL` / `until` | — | end date `YYYY-MM-DD` (CLI `--until`) |

CLI-only flags: `-c/--config`, `-v/--verbose`, `--since`, `--until`,
`--download-files`, `--no-watermark`, `--dry-run`.

---

## 9. Output Schema

### `messages.ndjson` (one JSON object per line)

| Field | Type | Description |
|---|---|---|
| `channel_id` | string | Slack channel ID |
| `channel_name` | string | channel name |
| `ts` | string | message timestamp (unique message ID) |
| `datetime_utc` | string | ISO 8601 UTC |
| `user_id` | string | author user/bot ID |
| `thread_ts` | string\|null | parent thread ts (null if top-level) |
| `text` | string | message text |
| `type` / `subtype` | string | message type / subtype |
| `reactions` | json\|null | reaction data |
| `reply_count` | int | thread reply count |
| `downloaded_files` | json\|absent | present when files were downloaded for the message |

> `raw` (original payload) lives in `raw.ndjson`, keyed by `channel_id` + `ts`.

### `_files_index.json` (array)
`file_id, file_name, local_path, channel_id, channel_name, sender_user_id,
message_ts, datetime_utc, thread_ts, message_text, filetype, size_bytes`

### `_users.json` (object) — `user_id → {id, display_name, real_name, email}`

### `.state/watermarks.json`
`{ "<channel_id>": { "watermark": "<ts>", "progress": { "params", "low", "high" } } }`
`progress` is present only while a descent is in flight (resume marker).

---

## 10. Required Slack Scopes (user token)

Minimum (public channels, default): `channels:history` · `channels:read` · `users:read`.
Add for more: `groups:history` + `groups:read` (private, with `channel_types=...,private_channel`)
· `users:read.email` (pseudonymization) · `files:read` (file download)
· `im:history` / `mpim:history` (DMs, with `im` / `mpim` in `channel_types`).
Missing private scope degrades to public automatically rather than failing.

---

## 11. Known Limitations

- **No exact message count** from Slack → estimates are order-of-magnitude.
- **New replies to old threads** (parent older than the watermark) aren't re-detected
  on incremental runs; run `--no-watermark`/`--since` periodically to refresh.
- **In-run network resilience** relies on slack_sdk's single connection-error retry
  plus app-level 429/transient retry; deeper outages defer to next-run resume.
- **At-least-once** writes on NDJSON (possible duplicate boundary page on resume).
- **Single token / single process** — no horizontal sharding across tokens yet.
- **Deleted messages / retention** — only non-deleted messages within the workspace
  retention window are returned by Slack.

---

## 12. Deployment / Scheduling

One-shot CLI; schedule with cron, GitHub Actions, Azure Functions Timer, or
Windows Task Scheduler (see README). For CI/serverless, **persist `.state/`**
between runs (commit, cache action, or external store) so incremental sync and
resume work across invocations.
