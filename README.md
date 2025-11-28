# addwikigeolocation
Bot/script to enrich Commons images with GPS metadata. It reads geolocation from the file page coordinates (with EXIF GPS as fallback) and writes it into the local file's EXIF GPS block, with safeguards to avoid overwriting images that already have GPS.

## What it does
- Pulls uploads from a user, partitions them into:
  - files with page coordinates but missing EXIF GPS (to update EXIF);
  - files with EXIF GPS but missing page coordinates (report only, for template addition).
- Shuffles the list to update EXIF, processes up to a configurable max.
- Reads GPS from the file page coordinates (`prop=coordinates`), falling back to EXIF metadata only if needed.
- Writes GPS into EXIF only when the EXIF is missing GPS; otherwise skips. Logs counts of updated/skipped/errored.
- Uses jittered sleeps and a per-minute cap to avoid hammering the API.
- Saves scan results (needs EXIF / needs template) to a JSON file; supports resume and dry-run.
- Downloads into a temp directory by default and removes files after processing to avoid filling disk.
- Optional upload back to Commons via `--upload`.

## Requirements
- Python 3.9+
- Packages: `requests`, `Pillow`, `piexif`, `GPSPhoto`, `mwclient`
  ```sh
  pip install requests Pillow piexif GPSPhoto mwclient
  ```

## Credentials
- Preferred: set environment variables `COMMONS_USER` and `COMMONS_PASS`.
- Optional: set `COMMONS_TARGET_USER` to scan uploads from a different user (defaults to the login user).
- Interactive fallback: if env vars are absent, the script will prompt for username and password (password is hidden with `getpass`).
- A sample `.env.example` is provided; keep your real `.env` out of git.

## Running
```sh
# optional: export credentials first
export COMMONS_USER=YourUser
export COMMONS_PASS=YourPassword

python addgeolocation.py \
  --target-user YourUser \
  --count 10 \
  --output gps_scan.json \
  --resume \
  --upload \
  --download-dir /tmp/addgeo \
  # --dry-run  # use to only list actions
```

Defaults:
- Max edits per run: `--count` (default 19)
- Base sleep: `--sleep` (default 10s) with jitter; per-minute cap: `--max-edits-per-min` (default 30)
- Scan file: `--output` (default `gps_scan.json`), use `--resume` to reuse it
- Dry-run: `--dry-run` to only list counts and sample items
- Download directory: defaults to a temporary directory; use `--download-dir` to override (files are cleaned after each item)
- Upload: off by default; enable with `--upload`

The script prints a summary: updated, skipped (already had GPS), skipped (no GPS source), and errors.

## Notes
- Identify your bot in the User-Agent if you change HTTP calls; Commons requires clear identification.
- Avoid committing real credentials; `.env` and `config.local.json` are gitignored by default.
