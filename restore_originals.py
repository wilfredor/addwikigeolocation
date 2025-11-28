from __future__ import annotations

import csv
import logging
import time
from pathlib import Path
from typing import Optional

import typer
from tqdm import tqdm

from commons_client import CommonsClient, UploadInfo
from datetime import datetime, timezone, timedelta

app = typer.Typer(add_completion=False)


def load_file_list(path: Path) -> list[UploadInfo]:
    uploads: list[UploadInfo] = []
    if path.suffix.lower() == ".csv":
        with path.open() as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                title = row.get("title")
                if not title:
                    continue
                oldid = row.get("oldid")
                oid_int = None
                if oldid:
                    try:
                        oid_int = int(oldid)
                    except ValueError:
                        pass
                uploads.append(UploadInfo(title=title, has_coords=False, has_exif_gps=False, oldid=oid_int))
    else:
        with path.open() as fh:
            for line in fh:
                title = line.strip()
                if title:
                    uploads.append(UploadInfo(title=title, has_coords=False, has_exif_gps=False))
    return uploads


@app.command()
def main(
    file_list: Optional[Path] = typer.Option(None, "--file-list", help="CSV (title,oldid) or plain text list of files to restore"),
    download_dir: Optional[Path] = typer.Option(None, "--download-dir", help="Directory to store downloads (defaults to temp)"),
    commons_user: str = typer.Option(
        None,
        "--commons-user",
        envvar="COMMONS_USER",
        prompt="Commons username",
    ),
    commons_pass: str = typer.Option(
        None,
        "--commons-pass",
        envvar="COMMONS_PASS",
        prompt=True,
        hide_input=True,
    ),
    comment: str = typer.Option("Restoring original version", "--comment", help="Upload comment to use"),
    max_per_min: int = typer.Option(30, "--max-per-min", help="Max uploads per minute"),
    since: Optional[str] = typer.Option(None, "--since", help="ISO timestamp to limit uploads (default: start of today UTC)"),
):
    """Restore files from a given list (or auto by user uploads in a time window)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    client = CommonsClient(commons_user, commons_pass, download_dir=str(download_dir) if download_dir else None)
    if since is None:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        since = today.strftime("%Y-%m-%dT%H:%M:%SZ")

    if file_list:
        uploads = load_file_list(file_list)
    else:
        logging.info("Auto mode: listing uploads for %s since %s", commons_user, since)
        uploads, _ = client.list_uploads(commons_user, since=since)
        # For each upload, set URL to previous revision
        for u in uploads:
            prev_url = client.get_previous_revision_url(u.title)
            u.url = prev_url

    progress = tqdm(total=len(uploads), unit="file", desc="Restoring", colour="blue")
    timestamps = []
    success = 0
    errors = 0
    for u in uploads:
        try:
            local = client.download_file(u)
            if not local:
                errors += 1
                progress.write(f"Could not download {u.title} (oldid={u.oldid})")
                progress.update(1)
                continue
            client.upload_file(u, local, comment=comment)
            success += 1
        except Exception as exc:
            errors += 1
            progress.write(f"Error restoring {u.title}: {exc}")
            logging.exception("Error restoring %s", u.title)
        finally:
            if 'local' in locals() and local:
                client.cleanup_file(local)
        progress.update(1)
        now = time.time()
        timestamps = [t for t in timestamps if now - t < 60]
        if len(timestamps) >= max_per_min:
            time.sleep(60 - (now - timestamps[0]))
        timestamps.append(time.time())
    progress.close()
    client.cleanup()
    print(f"Done. Restored: {success}, errors: {errors}")


if __name__ == "__main__":
    app()
