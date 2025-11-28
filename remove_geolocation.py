from __future__ import annotations

import csv
import logging
import re
import time
from pathlib import Path
from typing import List, Optional, Set

import typer
from tqdm import tqdm
import piexif

from commons_client import CommonsClient, UploadInfo

app = typer.Typer(add_completion=False)


def load_file_list(path: Path) -> List[str]:
    titles: List[str] = []
    if path.suffix.lower() == ".csv":
        with path.open() as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                title = row.get("title")
                if title:
                    titles.append(title)
    else:
        with path.open() as fh:
            for line in fh:
                title = line.strip()
                if title:
                    titles.append(title)
    return titles


def strip_geo_templates(text: str) -> tuple[str, bool]:
    """Remove common geolocation templates from wikitext."""
    patterns = [
        r"\{\{\s*[Ll]ocation[^}]*\}\}",
        r"\{\{\s*[Oo]bject\s+[Ll]ocation[^}]*\}\}",
        r"\{\{\s*[Cc]oord[^}]*\}\}",
    ]
    modified = False
    new_text = text
    for pat in patterns:
        new_text, n = re.subn(pat, "", new_text)
        if n:
            modified = True
    # Collapse multiple blank lines
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    return new_text, modified


def remove_exif_gps(file_path: Path) -> bool:
    """Return True if GPS was removed or was absent."""
    file_str = str(file_path)
    exif_dict = piexif.load(file_str)
    if "GPS" in exif_dict and exif_dict["GPS"]:
        exif_dict["GPS"] = {}
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, file_str)
        return True
    return False


@app.command()
def main(
    file_list: Optional[Path] = typer.Option(None, "--file-list", help="CSV (title) or plain text list of files"),
    category: Optional[str] = typer.Option(None, "--category", help="Category name (without 'Category:' prefix)"),
    max_depth: int = typer.Option(1, "--max-depth", help="Category recursion depth"),
    author_filter: Optional[str] = typer.Option(None, "--author-filter", help="Filter by author name (extmetadata)"),
    remove_exif: bool = typer.Option(True, "--remove-exif/--keep-exif", help="Remove EXIF GPS"),
    remove_page: bool = typer.Option(True, "--remove-page/--keep-page", help="Remove page geolocation templates"),
    apply: bool = typer.Option(False, "--apply", help="Apply changes (default: dry-run)"),
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
    download_dir: Optional[Path] = typer.Option(None, "--download-dir", help="Directory for downloads (temp by default)"),
    max_per_min: int = typer.Option(30, "--max-per-min", help="Max uploads per minute"),
):
    """Remove GPS info (EXIF and page templates) from files."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not file_list and not category:
        raise typer.Exit("Provide --file-list or --category")

    client = CommonsClient(commons_user, commons_pass, download_dir=str(download_dir) if download_dir else None)
    uploads: List[UploadInfo] = []
    if file_list:
        titles = load_file_list(file_list)
        uploads = client.fetch_uploads_for_titles(titles)
    else:
        uploads = client.list_category_files(category, max_depth=max_depth)
    # Filter by author if requested
    if author_filter:
        uploads = [u for u in uploads if u.author and author_filter.lower() in u.author.lower()]

    progress = tqdm(total=len(uploads), desc="Removing geo", unit="file", colour="yellow")
    timestamps: List[float] = []
    done = 0
    errors = 0
    for u in uploads:
        local = None
        try:
            changed = False
            if remove_exif:
                local = client.download_file(u)
                if local:
                    if remove_exif_gps(local):
                        changed = True
                    if apply:
                        client.upload_file(u, local, comment="Removing geolocation (EXIF)")
                else:
                    progress.write(f"Skip download for {u.title}")
            if remove_page:
                page = client._site.pages[u.title]  # type: ignore
                text = page.text()
                new_text, modified = strip_geo_templates(text)
                if modified and apply:
                    page.save(new_text, summary="Removing geolocation templates")
                    changed = True
            if changed or not apply:
                done += 1
        except Exception as exc:
            errors += 1
            progress.write(f"Error on {u.title}: {exc}")
            logging.exception("Error removing geo from %s", u.title)
        finally:
            if local:
                client.cleanup_file(local)
        progress.update(1)
        now = time.time()
        timestamps = [t for t in timestamps if now - t < 60]
        if len(timestamps) >= max_per_min:
            time.sleep(60 - (now - timestamps[0]))
        timestamps.append(time.time())
    progress.close()
    client.cleanup()
    print(f"Done. Processed: {len(uploads)}, successful/preview: {done}, errors: {errors}, apply={apply}")


if __name__ == "__main__":
    app()
