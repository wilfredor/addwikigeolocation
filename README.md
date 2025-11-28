# addwikigeolocation
Bot/script to enrich Commons images with GPS metadata. It reads geolocation from the file page coordinates (with EXIF GPS as fallback) and writes it into the local file's EXIF GPS block, with safeguards to avoid overwriting images that already have GPS. Now organized in small modules with a Typer CLI and resumable scans.

## What it does
- Pulls files from either uploads (logevents) or a category (with optional recursion), deduplicates, and partitions into:
  - files with page coordinates but missing EXIF GPS (to update EXIF);
  - files with EXIF GPS but missing page coordinates (report only).
- Filters to JPEGs and, optionally, by author (extmetadata `Artist`/`Author`).
- Shuffles and processes the EXIF-missing list up to a configurable max, showing progress `[x/total]`.
- Reads GPS from page coordinates, falling back to EXIF if needed; writes EXIF only when missing GPS.
- Resumable scans: stores lists and continuation token in `gps_scan.json` and updates after each batch/item.
- Uses jittered sleeps and per-minute cap; downloads to temp dir by default and cleans up.
- Optional upload back to Commons via `--upload`.

## Requirements
- Python 3.9+
- Install deps (via pyproject):
  ```sh
  pip install .
  ```

## Credentials
- Preferred: set environment variables `COMMONS_USER` and `COMMONS_PASS`.
- Optional: set `COMMONS_TARGET_USER` to scan uploads from a different user (defaults to the login user).
- Interactive fallback: if env vars are absent, the script will prompt for username and password (password is hidden with `getpass`).
- A sample `.env.example` is provided; keep your real `.env` out of git.

## Running
```sh
export COMMONS_USER=YourUser
export COMMONS_PASS=YourPassword

python addgeolocation.py \
  --target-user YourUser \  # or --category "Category:Foo" --max-depth 2
  --author-filter YourUser  # default is the target user
  --count 10 \
  --state-file gps_scan.json \
  --resume \
  --upload \
  --download-dir /tmp/addgeo \
  # --dry-run   # to only scan/list actions
```

Defaults:
- Max edits per run: `--count` (19)
- Base sleep: `--sleep` (10s) with jitter; per-minute cap: `--max-edits-per-min` (30)
- State file: `--state-file` (`gps_scan.json`) stores lists + continuation token; `--resume/--no-resume` controls reuse
- Dry-run: `--dry-run` to only scan/list
- Download directory: temp dir by default; override with `--download-dir`
- Upload: off by default; enable with `--upload`
- Category scan: use `--category` with `--max-depth` to recurse subcats
- Author filter: use `--author-filter` (defaults to target user) to match extmetadata author

The script prints a summary: updated, skipped (already had GPS), skipped (no GPS source), and errors.

## Notes
- Identify your bot in the User-Agent if you change HTTP calls; Commons requires clear identification.
- Avoid committing real credentials; `.env` and `config.local.json` are gitignored by default.
