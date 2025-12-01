from __future__ import annotations

import csv
import logging
import re
import time
from pathlib import Path
from typing import Optional, List
import getpass
import typer

from commons_client import CommonsClient, UploadInfo, valid_coordinates

app = typer.Typer(add_completion=False)

# Templates de localização que queremos detectar
GPS_TEMPLATES_RE = re.compile(
    r"\{\{\s*(Object location(?: dec)?|Camera location(?: dec)?|Location dec)",
    re.IGNORECASE,
)


def read_titles_from_file(file_list: Path) -> List[str]:
    titles: List[str] = []
    if file_list.suffix.lower() == ".csv":
        with file_list.open() as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                title = row.get("title")
                if title:
                    titles.append(title)
    else:
        with file_list.open() as fh:
            for line in fh:
                title = line.strip()
                if title:
                    titles.append(title)
    return titles


def extract_exif_gps(client: CommonsClient, title: str):
    """
    Lê GPS do EXIF via API (imageinfo/metadata) e converte para float.
    Usa o helper CommonsClient._get_lat_lon_gps.
    """
    data = client._site.api(
        "query",
        prop="imageinfo",
        titles=f"File:{title}",
        iiprop="metadata",
        format="json",
    )
    if not data or "query" not in data or "pages" not in data["query"]:
        return None, None

    page = next(iter(data["query"]["pages"].values()))
    imageinfo = page.get("imageinfo", [])
    if not imageinfo:
        return None, None

    metadata = imageinfo[0].get("metadata", [])
    lat = CommonsClient._get_lat_lon_gps("GPSLatitude", metadata)
    lon = CommonsClient._get_lat_lon_gps("GPSLongitude", metadata)

    if not valid_coordinates(lat, lon):
        return None, None
    return lat, lon


def has_gps_template(wikitext: str) -> bool:
    if not wikitext:
        return False
    return bool(GPS_TEMPLATES_RE.search(wikitext))


def build_camera_location_template(lat: float, lon: float) -> str:
    # usa versão decimal do template
    return "{{Camera location dec|{:.6f}|{:.6f}}}\n".format(lat, lon)


def edit_page(
    client: CommonsClient,
    title: str,
    new_text: str,
    summary: str,
) -> bool:
    full_title = title if title.startswith("File:") else f"File:{title}"
    try:
        res = client._site.api(
            "edit",
            title=full_title,
            text=new_text,
            token=client._csrf_token,
            summary=summary,
            bot=True,
            format="json",
        )
    except Exception as exc:
        logging.error("Edit failed for %s: %s", full_title, exc)
        return False

    if "error" in res:
        logging.error("Edit error for %s: %s", full_title, res["error"])
        return False

    result = res.get("edit", {}).get("result")
    if result != "Success":
        logging.warning("Unexpected edit result for %s: %r", full_title, result)
        return False

    return True


@app.command()
def main(
    target_user: Optional[str] = typer.Option(
        None, "--target-user", help="Uploader to scan (defaults to login user)"
    ),
    count: int = typer.Option(
        25, "--count", help="Max pages to modify"
    ),
    sleep: float = typer.Option(
        5.0, "--sleep", help="Seconds to sleep between edits"
    ),
    category: Optional[str] = typer.Option(
        None, "--category", help="Scan a category instead of uploader"
    ),
    max_depth: int = typer.Option(
        1, "--max-depth", help="Category recursion depth"
    ),
    author_filter: Optional[str] = typer.Option(
        None, "--author-filter", help="Filter by author name (defaults to target user)"
    ),
    file_list: Optional[Path] = typer.Option(
        None, "--file-list", help="Process a specific list of files (CSV/plain)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Only list actions, do not edit pages"
    )
):
    """
    Adiciona {{Camera location dec}} usando GPS do EXIF quando:
    - o arquivo tem GPS no EXIF
    - e a página NÃO tem template de localização.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    commons_user = input("Commons username: ")
    commons_pass = getpass.getpass("Commons password: ")

    client = CommonsClient(commons_user, commons_pass)

    try:
        target = target_user or commons_user
        author = author_filter or target

        uploads: List[UploadInfo] = []

        if file_list:
            titles = read_titles_from_file(file_list)
            uploads = client.fetch_uploads_for_titles(titles)
        elif category:
            uploads = client.list_category_files(category, max_depth=max_depth)
        else:
            uploads, _ = client.list_uploads(target)

        # Filtro básico
        filtered: List[UploadInfo] = []
        for u in uploads:
            if not u.title.lower().endswith((".jpg", ".jpeg")):
                continue
            if author and u.author and author.lower() not in u.author.lower():
                continue
            if not u.has_exif_gps:
                continue
            filtered.append(u)

        logging.info("Found %d JPEG uploads with EXIF GPS to check.", len(filtered))

        edits_done = 0
        for upload in filtered:
            if edits_done >= count:
                break

            wikitext = client.fetch_wikitext(upload.title) or ""
            if has_gps_template(wikitext):
                logging.info("Skipping %s (already has location template).", upload.title)
                continue

            lat, lon = extract_exif_gps(client, upload.title)
            if lat is None or lon is None:
                logging.info("Skipping %s (could not read EXIF GPS).", upload.title)
                continue

            tpl = build_camera_location_template(lat, lon)
            new_text = tpl + wikitext

            if dry_run:
                print(f"[DRY RUN] Would add {tpl.strip()} to File:{upload.title}")
                edits_done += 1
                continue

            ok = edit_page(
                client,
                upload.title,
                new_text,
                summary="Adding {{Camera location dec}} from EXIF GPS (bot).",
            )
            if ok:
                logging.info(
                    "Added Camera location template to %s with lat=%.6f lon=%.6f",
                    upload.title,
                    lat,
                    lon,
                )
                edits_done += 1
                time.sleep(sleep)
            else:
                logging.error("Failed to edit %s", upload.title)

        logging.info("Done. Performed %d edits.", edits_done)
    finally:
        client.close()


if __name__ == "__main__":
    app()
