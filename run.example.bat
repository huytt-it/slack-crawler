@echo off
setlocal

:: ============================================================
:: SlackCrawler — Quick Run Script
::
:: Copy this file to run.bat and fill in your values.
:: run.bat is in .gitignore so your token stays safe.
::
:: Usage:
::   run.bat                                       (sync all)
::   run.bat --since 2025-01-01                    (from date)
::   run.bat --since 2025-01-01 --until 2025-06-30 (date range)
::   run.bat --download-files                      (with files)
:: ============================================================

:: ===================
::  REQUIRED
:: ===================
set SLACK_TOKEN=

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
set DOWNLOAD_FILES=true

:: Incremental sync: true = only fetch new messages, false = re-fetch from lookback_days
set USE_WATERMARK=false

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
