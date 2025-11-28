from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Optional, List

import typer
from tqdm import tqdm
import mwclient

from commons_client import CommonsClient

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
                if line.strip():
                    titles.append(line.strip())
    return titles


def fetch_previous_wikitext(site: mwclient.Site, title: str) -> Optional[tuple[str, str]]:
    full_title = title if title.startswith("File:") else f"File:{title}"
    data = site.api(
        "query",
        prop="revisions",
        titles=full_title,
        rvprop="ids|timestamp|user|comment|content",
        rvslots="main",
        rvlimit=2,
        format="json",
    )
    if not data or "query" not in data or "pages" not in data["query"]:
        return None
    page = next(iter(data["query"]["pages"].values()))
    revs = page.get("revisions", [])
    if len(revs) < 2:
        return None
    prev = revs[1]
    slots = prev.get("slots", {})
    main = slots.get("main", {})
    content = main.get("*") or main.get("content")
    prev_user = prev.get("user", "")
    return content, prev_user


@app.command()
def main(
    file_list: Optional[Path] = typer.Option(None, "--file-list", help="CSV or text file with titles to rollback"),
    category: Optional[str] = typer.Option(None, "--category", help="Category name (without 'Category:' prefix)"),
    max_depth: int = typer.Option(1, "--max-depth", help="Category recursion depth"),
    apply: bool = typer.Option(False, "--apply", help="Apply rollback (default dry-run)"),
    force: bool = typer.Option(False, "--force", help="Rollback even if last editor is different"),
    log_csv: Optional[Path] = typer.Option(None, "--log-csv", help="Optional CSV log"),
):
    """
    Roll back file descriptions to the previous revision.
    Default is dry-run; use --apply to save. Requires COMMONS_USER/PASS env vars.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    commons_user = Path(".env")
    commons_user = None  # placeholder to appease type checkers
    # Env vars
    import os

    commons_user = os.getenv("COMMONS_USER")
    commons_pass = os.getenv("COMMONS_PASS")
    if not commons_user or not commons_pass:
        raise typer.Exit("COMMONS_USER and COMMONS_PASS must be set in env.")

    client = CommonsClient(commons_user, commons_pass)
    uploads = []
    if file_list:
        titles = load_file_list(file_list)
        uploads = client.fetch_uploads_for_titles(titles)
    elif category:
        uploads = client.list_category_files(category, max_depth=max_depth)
    else:
        raise typer.Exit("Provide --file-list or --category")

    if log_csv:
        exists = log_csv.exists()
        with log_csv.open("a", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["title", "status", "reason"])
            if not exists:
                writer.writeheader()

    progress = tqdm(total=len(uploads), desc="Rollback", unit="file", colour="red")
    done = 0
    errors = 0
    for u in uploads:
        full_title = u.title if u.title.startswith("File:") else f"File:{u.title}"
        try:
            prev = fetch_previous_wikitext(client._site, u.title)
            if not prev:
                reason = "no previous revision"
                progress.write(f"Skipping {full_title}: {reason}")
                if log_csv:
                    with log_csv.open("a", newline="") as fh:
                        writer = csv.DictWriter(fh, fieldnames=["title", "status", "reason"])
                        writer.writerow({"title": full_title, "status": "skipped", "reason": reason})
                progress.update(1)
                continue
            content, prev_user = prev
            if not force and prev_user and prev_user != commons_user:
                reason = f"last editor {prev_user} differs"
                progress.write(f"Skipping {full_title}: {reason}")
                if log_csv:
                    with log_csv.open("a", newline="") as fh:
                        writer = csv.DictWriter(fh, fieldnames=["title", "status", "reason"])
                        writer.writerow({"title": full_title, "status": "skipped", "reason": reason})
                progress.update(1)
                continue
            if apply:
                page = client._site.pages[full_title]
                page.save(content, summary="Rollback to previous description revision")
                done += 1
                if log_csv:
                    with log_csv.open("a", newline="") as fh:
                        writer = csv.DictWriter(fh, fieldnames=["title", "status", "reason"])
                        writer.writerow({"title": full_title, "status": "rolled_back", "reason": ""})
            else:
                progress.write(f"Dry-run {full_title}: would rollback to previous revision")
                done += 1
                if log_csv:
                    with log_csv.open("a", newline="") as fh:
                        writer = csv.DictWriter(fh, fieldnames=["title", "status", "reason"])
                        writer.writerow({"title": full_title, "status": "dry-run", "reason": ""})
        except Exception as exc:
            errors += 1
            progress.write(f"Error on {full_title}: {exc}")
            logging.exception("Error rolling back %s", full_title)
            if log_csv:
                with log_csv.open("a", newline="") as fh:
                    writer = csv.DictWriter(fh, fieldnames=["title", "status", "reason"])
                    writer.writerow({"title": full_title, "status": "error", "reason": str(exc)})
        progress.update(1)
    progress.close()
    client.cleanup()
    print(f"Done. Processed: {len(uploads)}, rolled back/dry-run: {done}, errors: {errors}, apply={apply}")


if __name__ == "__main__":
    app()
