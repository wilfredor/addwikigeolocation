# addwikigeolocation
Bot/script to enrich Commons images with GPS metadata. It reads geolocation already present on Commons (extmetadata) and writes it into the local file's EXIF GPS block, with safeguards to avoid overwriting images that already have GPS.

## What it does
- Pulls JPEGs from a category, shuffles the list, and processes up to `COUNT_NUMBER` items.
- Reads GPS from the file page coordinates (`prop=coordinates`), falling back to `extmetadata` only if needed.
- Writes GPS into EXIF only when the EXIF is missing GPS; otherwise skips. Logs counts of updated/skipped/errored.
- Uses jittered sleeps and a per-minute cap to avoid hammering the API.

## Requirements
- Python 3.9+
- Packages: `requests`, `Pillow`, `piexif`, `GPSPhoto`
  ```sh
  pip install requests Pillow piexif GPSPhoto
  ```

## Credentials
- Preferred: set environment variables `COMMONS_USER` and `COMMONS_PASS`.
- Interactive fallback: if env vars are absent, the script will prompt for username and password (password is hidden with `getpass`).
- A sample `.env.example` is provided; keep your real `.env` out of git.

## Running
```sh
# optional: export credentials first
export COMMONS_USER=YourUser
export COMMONS_PASS=YourPassword

python addgeolocation.py
```

Defaults:
- Category: `Quality_images_by_Wilfredor` (edit `addgeolocation.py` to change)
- Max edits per run: `COUNT_NUMBER` (19)
- Base sleep: `SLEEP_SECCONDS` (10s) with jitter; per-minute cap: `MAX_EDITS_PER_MIN` (30)

The script prints a summary: updated, skipped (already had GPS), skipped (no GPS source), and errors.

## Notes
- Identify your bot in the User-Agent if you change HTTP calls; Commons requires clear identification.
- Avoid committing real credentials; `.env` and `config.local.json` are gitignored by default.
