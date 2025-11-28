from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Tuple

from tqdm import tqdm
import logging

from commons_client import CommonsClient, UploadInfo
from scanner import ScanState, save_state


def rate_limit_sleep(edit_timestamps, max_edits_per_min, base_sleep):
    now = time.time()
    edit_timestamps[:] = [t for t in edit_timestamps if now - t < 60]
    if len(edit_timestamps) >= max_edits_per_min:
        sleep_for = 60 - (now - edit_timestamps[0])
        time.sleep(max(sleep_for, 1))
    edit_timestamps.append(time.time())
    time.sleep(random.uniform(base_sleep * 0.5, base_sleep * 1.5))


def process_needs_exif(
    client: CommonsClient,
    state: ScanState,
    state_path: Path,
    count: int,
    base_sleep: float,
    max_edits_per_min: int,
    upload: bool,
) -> Tuple[int, int, int, int]:
    edits_count = count
    updated = 0
    skipped_has_gps = 0
    skipped_no_gps = 0
    errors = 0

    images = list(state.needs_exif)
    random.shuffle(images)
    edit_timestamps = []
    total_images = len(images)

    progress = tqdm(total=total_images, unit="file", desc="Processing", leave=True, colour="green")

    for idx, upload_info in enumerate(images, start=1):
        local_path = None
        try:
            if not upload_info.has_coords:
                skipped_no_gps += 1
                progress.write(f"[{idx}/{total_images}] Skipping {upload_info.title} (no page coordinates)")
                state.needs_exif.remove(upload_info)
                save_state(state_path, state)
                progress.update(1)
                continue
            if upload_info.has_exif_gps:
                skipped_has_gps += 1
                progress.write(f"[{idx}/{total_images}] Skipping {upload_info.title} (GPS already present)")
                state.needs_exif.remove(upload_info)
                save_state(state_path, state)
                progress.update(1)
                continue

            progress.write(f"[{idx}/{total_images}] processing: {upload_info.title}")
            local_path = client.download_file(upload_info)
            if not local_path:
                errors += 1
                progress.write(f" Could not download {upload_info.title}")
            else:
                try:
                    client.write_exif(upload_info, local_path)
                    if upload:
                        client.upload_file(upload_info, local_path)
                    updated += 1
                    edits_count -= 1
                except Exception as exc:
                    errors += 1
                    progress.write(f"Error writing/uploading {upload_info.title}: {exc}")
            if upload_info in state.needs_exif:
                state.needs_exif.remove(upload_info)
            save_state(state_path, state)
        except Exception as exc:
            errors += 1
            progress.write(f"Error processing {upload_info.title}: {exc}")
            logging.exception("Error processing %s", upload_info.title)
        finally:
            if local_path:
                client.cleanup_file(local_path)

        progress.update(1)
        if edits_count == 0:
            break
        rate_limit_sleep(edit_timestamps, max_edits_per_min, base_sleep)

    progress.close()

    return updated, skipped_has_gps, skipped_no_gps, errors
