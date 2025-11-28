import os
import random
import sys
import time
import getpass
from configConnection import ConfigConnection

COUNT_NUMBER = 19
SLEEP_SECCONDS = 10
MAX_EDITS_PER_MIN = 30


def _get_credential(env_name, prompt_text, secret=False):
    value = os.getenv(env_name)
    if value:
        return value
    return getpass.getpass(prompt_text) if secret else input(prompt_text)


commons_user = _get_credential("COMMONS_USER", "Commons username: ")
commons_pass = _get_credential("COMMONS_PASS", "Commons password: ", secret=True)
target_user = _get_credential(
    "COMMONS_TARGET_USER",
    f"Target uploader (default {commons_user}): ",
)
if not target_user:
    target_user = commons_user

c = ConfigConnection(
    commons_user,
    commons_pass,
    )

# Sample in category
edits_count = COUNT_NUMBER
updated = 0
skipped_has_gps = 0
skipped_no_gps = 0
errors = 0
uploads = c.get_user_uploads_with_gps(target_user)
needs_template = [
    u["title"] for u in uploads if u["has_exif_gps"] and not u["has_coords"]
]
needs_exif = [
    u["title"] for u in uploads if u["has_coords"] and not u["has_exif_gps"]
]

print(
    f"Found {len(uploads)} uploads for {target_user}: "
    f"{len(needs_exif)} need EXIF GPS, {len(needs_template)} need page template."
)
if needs_template:
    print(f"Examples needing template (up to 5): {needs_template[:5]}")

images = needs_exif
random.shuffle(images)
edit_timestamps = []
for img in images:
    c.set_filename(img)
    if not c.can_set_metadata_location_gps():
        if c.metadata() or c.extmetadata():
            skipped_has_gps += 1
            print(f"Skipping {img} (GPS already present)")
        else:
            skipped_no_gps += 1
            print(f"No GPS data for {img}, skipping")
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
    except Exception as exc:
        errors += 1
        print(f"Error processing {img}: {exc}")
    if edits_count == 0:
        break
    now = time.time()
    edit_timestamps = [t for t in edit_timestamps if now - t < 60]
    if len(edit_timestamps) >= MAX_EDITS_PER_MIN:
        # wait until we fall under the per-minute cap
        sleep_for = 60 - (now - edit_timestamps[0])
        time.sleep(max(sleep_for, 1))
    edit_timestamps.append(time.time())
    time.sleep(random.uniform(SLEEP_SECCONDS * 0.5, SLEEP_SECCONDS * 1.5))

print(
    f"Finished. Updated: {updated}, skipped (has GPS): {skipped_has_gps}, "
    f"skipped (no GPS source): {skipped_no_gps}, errors: {errors}."
)

