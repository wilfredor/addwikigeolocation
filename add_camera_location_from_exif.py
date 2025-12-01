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
    r"\{\{\s*("
    r"Object location(?: dec)?|"      # {{Object location}}, {{Object location dec}}
    r"Camera location(?: dec)?|"      # {{Camera location}}, {{Camera location dec}}
    r"Location(?: dec)?|"             # {{Location}}, {{Location dec}}
    r"Coord(?:inates)?"               # {{Coord}}, {{Coordinates}}
    r")\b",
    re.IGNORECASE,
)

# Linha com {{GPS EXIF}} (geralmente usada sozinha em uma linha)
GPS_EXIF_LINE_RE = re.compile(
    r"(?mi)^\s*\{\{\s*GPS\s+EXIF[^}]*\}\}\s*\n?"
)

REDIRECT_RE = re.compile(r"(?i)^\s*#redirect\b", re.MULTILINE)
FILEDESC_HEADING_RE = re.compile(r"(?im)^==\s*\{\{\s*int:filedesc\s*\}\}\s*==\s*$")

def is_redirect(wikitext: str) -> bool:
    if not wikitext:
        return False
    return bool(REDIRECT_RE.search(wikitext))

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


def remove_gps_exif_template(wikitext: str) -> str:
    """
    Remove linhas com {{GPS EXIF}} da wikitext.
    """
    return GPS_EXIF_LINE_RE.sub("", wikitext)


def build_camera_location_template(lat: float, lon: float) -> str:
    return "{{{{Camera location dec|{:.6f}|{:.6f}}}}}\n".format(lat, lon)


def insert_after_filedesc_heading(wikitext: str, tpl: str) -> str:
    """
    Insere o template logo após o heading =={{int:filedesc}}== se existir;
    caso contrário, adiciona no topo.
    """
    match = FILEDESC_HEADING_RE.search(wikitext)
    if not match:
        return tpl + wikitext

    insert_pos = match.end()
    prefix = wikitext[:insert_pos]
    suffix = wikitext[insert_pos:]

    if not prefix.endswith("\n"):
        prefix += "\n"
    if suffix.startswith("\n"):
        suffix = suffix[1:]

    return prefix + tpl + suffix

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
    Também remove {{GPS EXIF}} da página na mesma edição.
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
        # If --author-filter is provided as empty string, disable author filtering
        author = target if author_filter is None else author_filter

        uploads: List[UploadInfo] = []

        if file_list:
            titles = read_titles_from_file(file_list)
            uploads = client.fetch_uploads_for_titles(titles)
        elif category:
            uploads = client.list_category_files(category, max_depth=max_depth)
        else:
            uploads, _ = client.list_uploads(target)

        total_listed = len(uploads)
        skipped_non_jpeg = 0
        skipped_author = 0
        skipped_redirect = 0
        skipped_has_template = 0
        skipped_no_gps_read = 0
        gps_exif_present = 0
        gps_exif_removed = 0

        # Filtro básico
        filtered: List[UploadInfo] = []
        for u in uploads:
            if not u.title.lower().endswith((".jpg", ".jpeg")):
                skipped_non_jpeg += 1
                continue
            if author and u.author and author.lower() not in u.author.lower():
                skipped_author += 1
                continue
            filtered.append(u)

        total_candidates = len(filtered)
        max_to_process = min(total_candidates, count) if count > 0 else total_candidates
        logging.info(
            "Category/uploader returned %d items: %d non-JPEG, %d author-mismatch, %d remaining to check (processing up to %d).",
            total_listed,
            skipped_non_jpeg,
            skipped_author,
            total_candidates,
            max_to_process,
        )

        edits_done = 0
        processed = 0
        for upload in filtered:
            if processed >= max_to_process:
                break

            logging.info("[%d/%d] Checking %s", processed + 1, max_to_process, upload.title)

            wikitext = client.fetch_wikitext(upload.title) or ""
            has_gps_exif_tpl = bool(GPS_EXIF_LINE_RE.search(wikitext))
            if has_gps_exif_tpl:
                gps_exif_present += 1
            if is_redirect(wikitext):
                logging.info("Skipping %s (redirect page).", upload.title)
                skipped_redirect += 1
                processed += 1
                continue

            if has_gps_template(wikitext):
                logging.info("Skipping %s (already has location template).", upload.title)
                skipped_has_template += 1
                processed += 1
                continue

            lat, lon = extract_exif_gps(client, upload.title)
            if lat is None or lon is None:
                logging.info(
                    "Skipping %s (could not read EXIF GPS; upload.has_exif_gps=%s; GPS_EXIF_template=%s).",
                    upload.title,
                    upload.has_exif_gps,
                    has_gps_exif_tpl,
                )
                skipped_no_gps_read += 1
                processed += 1
                continue

            tpl = build_camera_location_template(lat, lon)
            cleaned_wikitext = remove_gps_exif_template(wikitext)
            new_text = insert_after_filedesc_heading(cleaned_wikitext, tpl)

            if dry_run:
                msg = f"[DRY RUN] Would add {tpl.strip()} to File:{upload.title}"
                if "GPS EXIF" in wikitext:
                    msg += " and remove {{GPS EXIF}}"
                print(msg)
                edits_done += 1
                processed += 1
                continue

            ok = edit_page(
                client,
                upload.title,
                new_text,
                summary="Adding {{Camera location dec}} from EXIF GPS and removing {{GPS EXIF}} (bot).",
            )
            if ok:
                logging.info(
                    "Updated %s: added Camera location template with lat=%.6f lon=%.6f and removed GPS EXIF if present",
                    upload.title,
                    lat,
                    lon,
                )
                if has_gps_exif_tpl:
                    gps_exif_removed += 1
                edits_done += 1
                processed += 1
                time.sleep(sleep)
            else:
                logging.error("Failed to edit %s", upload.title)
                processed += 1

        logging.info(
            "Done. Processed %d/%d candidates. Performed %d edits. Skipped: %d redirects, %d with existing location template, %d could not read EXIF GPS.",
            processed,
            max_to_process,
            edits_done,
            skipped_redirect,
            skipped_has_template,
            skipped_no_gps_read,
        )
        logging.info(
            "GPS EXIF templates seen: %d; removed via edit: %d.",
            gps_exif_present,
            gps_exif_removed,
        )
    finally:
        client.close()


if __name__ == "__main__":
    app()
