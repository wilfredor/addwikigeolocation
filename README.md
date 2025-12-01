# Commons toolbox CLI
CLI toolbox for Wikimedia Commons maintenance: add/remove geolocation (EXIF + page templates), translate descriptions with Argos, and restore/rollback file versions. Uses BotPassword credentials, optional `.env`, and CSV logs for traceability.

## Scripts overview
- `addgeolocation.py` — scans uploads or categories, finds JPEGs with page coordinates but missing EXIF GPS, writes GPS to EXIF, and (optionally) uploads the updated file back. Resumable via `gps_scan.json`, supports author filter, rate limits, and temp downloads cleanup.
- `remove_geolocation.py` — removes GPS from EXIF and/or page templates. Can run dry-run, EXIF-only, page-only, and has a guarded `--purge-history` flag (admin-only).
- `restore_originals.py` — restores a previous revision by explicit `oldid` (CSV) or by time window (`--since`). Optionally applies the edit or runs dry.
- `translate_descriptions.py` — adds missing translations (es, fr, pt, ru, zh, de) using Argos. Auto-detects source language from {{lang|...}} or falls back to `DEFAULT_SOURCE_LANG`. Logs incrementally to CSV; skips on missing models or abusefilter.
- Support modules: `commons_client.py` (API helpers), `processor.py` (EXIF and image ops), `scanner.py` (listing and state).

## Requirements
- Python 3.9+
- Install deps (via pyproject):
  ```sh
  pip install .
  ```

## Credentials
- Set `COMMONS_USER` and `COMMONS_PASS` (BotPassword recommended). A `.env.example` is provided; `.env` is gitignored and auto-loaded by scripts.
- Optional: `COMMONS_TARGET_USER` for scanning another uploader; `DEFAULT_SOURCE_LANG` for translations fallback.

## Running (key scripts)

### addgeolocation.py (add EXIF GPS)
Requirements: `COMMONS_USER`, `COMMONS_PASS`; JPEGs only; uses temp downloads; respects `gps_scan.json` for resume.
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

### add_camera_location_from_exif.py (add page template from EXIF GPS)
Adds `{{Camera location dec}}` to pages that have EXIF GPS but no location template; removes `{{GPS EXIF}}`; skips redirects. Prompts for Commons username/password (BotPassword recommended). `--count` limits how many files are processed (including skips), not how many edits are made.
```sh
# Scan one category (depth 1) and add template to up to 25 pages (default)
python add_camera_location_from_exif.py \
  --category "Quality images by Wilfredor" \
  --max-depth 1 \
  --count 25 \
  --dry-run   # drop this flag to actually edit

# Example to review up to 5000 images in a large category
python add_camera_location_from_exif.py \
  --category "YourCategoryName" \
  --max-depth 2 \
  --count 5000 \
  --sleep 2.0

# To disable author filtering (process all files in the category), pass an empty string
python add_camera_location_from_exif.py \
  --category "YourCategoryName" \
  --author-filter "" \
  --count 5000
```

### remove_geolocation.py (strip GPS)
Requirements: `COMMONS_USER`, `COMMONS_PASS`.
```sh
python remove_geolocation.py \
  --category "MyCategory" --max-depth 1 \
  --author-filter "YourName" \
  --remove-exif --remove-page \
  --apply    # default is dry-run
```
`--purge-history` is available but requires admin rights and is not automated (manual action recommended).

### restore_originals.py (lossless restore)
Requirements: `COMMONS_USER`, `COMMONS_PASS`; optionally a CSV (`title,oldid`) or `--since`.
```sh
python restore_originals.py \
  --since 2025-11-28T00:00:00Z \
  --comment "Restoring original version" \
  --apply   # remove for dry-run
# or provide a CSV with title,oldid via --file-list restore.csv
```

### translate_descriptions.py (Argos translations)
Requirements: `COMMONS_USER`, `COMMONS_PASS`; optional cloud backend `GOOGLE_TRANSLATE_KEY` or local `argostranslate` (install + models). Optional `DEFAULT_SOURCE_LANG` fallback.
```sh
export COMMONS_USER=YourBotUser   # e.g., Wilfredor@BotPassword
export COMMONS_PASS=YourBotPass
# optional fallback when no lang template present
export DEFAULT_SOURCE_LANG=es
# optional Google backend
export GOOGLE_TRANSLATE_KEY=your_key

# Translates descriptions for JPEGs in the category (depth 1)
python translate_descriptions.py \
  --category "Quality images by Wilfredor" \
  --log-csv translations_report.csv \
  --max-edits 20 \
  --apply    # omit to dry-run
```
Behavior:
- Source language is auto-detected from existing {{lang|...}}; if missing, falls back to `DEFAULT_SOURCE_LANG` (default: en).
- Targets are fixed to es, fr, pt, ru, zh, de.
- Backend: Google Translate if `GOOGLE_TRANSLATE_KEY` is set; otherwise local `argostranslate` with installed models (missing models will be skipped).
- Uses `COMMONS_USER` / `COMMONS_PASS` from env (or `.env` is read automatically).
- Writes incremental log rows to `--log-csv` as it runs.
- Optional: `--max-edits` to cap how many pages are updated in one run (processes all if omitted).

The script prints a summary: updated, skipped (already had GPS), skipped (no GPS source), and errors.

## Notes
- Identify your bot in the User-Agent if you change HTTP calls; Commons requires clear identification.
- Avoid committing real credentials; `.env` and `config.local.json` are gitignored by default.
