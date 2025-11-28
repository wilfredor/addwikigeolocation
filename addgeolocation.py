import argparse
import getpass
import json
import os
import random
import sys
import time
from pathlib import Path
from configConnection import ConfigConnection

DEFAULT_COUNT_NUMBER = 19
DEFAULT_SLEEP_SECONDS = 10
DEFAULT_MAX_EDITS_PER_MIN = 30
DEFAULT_OUTPUT = "gps_scan.json"


def _get_credential(env_name, prompt_text, secret=False):
    value = os.getenv(env_name)
    if value:
        return value
    return getpass.getpass(prompt_text) if secret else input(prompt_text)


def _parse_args():
    parser = argparse.ArgumentParser(description="Add GPS to EXIF from page coords.")
    parser.add_argument("--target-user", help="Uploader to scan (defaults to login user)")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT_NUMBER, help="Max edits to perform")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_SECONDS, help="Base sleep seconds")
    parser.add_argument("--max-edits-per-min", type=int, default=DEFAULT_MAX_EDITS_PER_MIN)
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Path to save scan results")
    parser.add_argument("--resume", action="store_true", help="Reuse existing scan file")
    parser.add_argument("--dry-run", action="store_true", help="Only list actions, do not modify files")
    return parser.parse_args()


def _load_scan(path: Path):
    if path.exists():
        with path.open() as fh:
            return json.load(fh)
    return None


def _save_scan(path: Path, needs_exif, needs_template):
    payload = {
        "needs_exif": list(needs_exif),
        "needs_template": list(needs_template),
    }
    with path.open("w") as fh:
        json.dump(payload, fh, indent=2)


def main():
    args = _parse_args()

    commons_user = _get_credential("COMMONS_USER", "Commons username: ")
    commons_pass = _get_credential("COMMONS_PASS", "Commons password: ", secret=True)
    target_user = args.target_user or os.getenv("COMMONS_TARGET_USER") or commons_user

    c = ConfigConnection(
        commons_user,
        commons_pass,
        )

    output_path = Path(args.output)
    needs_exif = []
    needs_template = []
    if args.resume:
        scan = _load_scan(output_path)
        if scan:
            needs_exif = scan.get("needs_exif", [])
            needs_template = scan.get("needs_template", [])

    if not needs_exif and not needs_template:
        uploads = c.get_user_uploads_with_gps(target_user)
        needs_template = [
            u["title"] for u in uploads if u["has_exif_gps"] and not u["has_coords"]
        ]
        needs_exif = [
            u["title"] for u in uploads if u["has_coords"] and not u["has_exif_gps"]
        ]
        _save_scan(output_path, needs_exif, needs_template)

    print(
        f"Uploads for {target_user}: {len(needs_exif)} need EXIF GPS, "
        f"{len(needs_template)} need page template."
    )
    if needs_template:
        print(f"Examples needing template (up to 5): {needs_template[:5]}")

    if args.dry_run:
        print("Dry run: exiting without modifications.")
        return

    edits_count = args.count
    updated = 0
    skipped_has_gps = 0
    skipped_no_gps = 0
    errors = 0

    images = list(needs_exif)
    random.shuffle(images)
    edit_timestamps = []
    for img in images:
        c.set_filename(img)
        if not c.can_set_metadata_location_gps():
            if c.metadata():
                skipped_has_gps += 1
                print(f"Skipping {img} (GPS already present)")
            else:
                skipped_no_gps += 1
                print(f"No GPS data for {img}, skipping")
            needs_exif.remove(img)
            _save_scan(output_path, needs_exif, needs_template)
            continue

        try:
            print("processing: ", c._filename)
            c.download_file_new()
            c.set_metadata_location_gps()
            '''
            c.upload_to_commons()
            '''
            edits_count -= 1
            updated += 1
            needs_exif.remove(img)
            _save_scan(output_path, needs_exif, needs_template)
        except Exception as exc:
            errors += 1
            print(f"Error processing {img}: {exc}")
        if edits_count == 0:
            break
        now = time.time()
        edit_timestamps = [t for t in edit_timestamps if now - t < 60]
        if len(edit_timestamps) >= args.max_edits_per_min:
            sleep_for = 60 - (now - edit_timestamps[0])
            time.sleep(max(sleep_for, 1))
        edit_timestamps.append(time.time())
        time.sleep(random.uniform(args.sleep * 0.5, args.sleep * 1.5))

    _save_scan(output_path, needs_exif, needs_template)
    print(
        f"Finished. Updated: {updated}, skipped (has GPS): {skipped_has_gps}, "
        f"skipped (no GPS source): {skipped_no_gps}, errors: {errors}."
    )


if __name__ == "__main__":
    main()

