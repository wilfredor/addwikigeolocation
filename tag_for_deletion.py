from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import List, Optional

import typer
from tqdm import tqdm

from commons_client import CommonsClient

app = typer.Typer(add_completion=False)


def load_titles(path: Path) -> List[str]:
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


@app.command()
def main(
    file_list: Path = typer.Option(..., "--file-list", help="CSV/text with page titles to tag (not necessarily File:)"),
    apply: bool = typer.Option(False, "--apply", help="Apply tag (default dry-run)"),
    reason: str = typer.Option("G7: Author requests deletion of page created in error", "--reason", help="Reason for delete tag"),
    log_csv: Optional[Path] = typer.Option(None, "--log-csv", help="Optional CSV log"),
):
    """
    Tag pages for deletion by adding {{delete|reason}} at the top.
    Default is dry-run; requires COMMONS_USER / COMMONS_PASS.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import os

    commons_user = os.getenv("COMMONS_USER")
    commons_pass = os.getenv("COMMONS_PASS")
    if not commons_user or not commons_pass:
        raise typer.Exit("COMMONS_USER and COMMONS_PASS must be set in env.")

    titles = load_titles(file_list)
    client = CommonsClient(commons_user, commons_pass)

    if log_csv:
        exists = log_csv.exists()
        with log_csv.open("a", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["title", "status", "reason"])
            if not exists:
                writer.writeheader()

    progress = tqdm(total=len(titles), desc="Tagging", unit="page", colour="cyan")
    tagged = 0
    errors = 0
    for title in titles:
        full_title = title if ":" in title else title  # allow any namespace, including File:
        try:
            page = client._site.pages[full_title]  # type: ignore
            text = client.fetch_wikitext(full_title) or page.text()
            tag = f"{{{{delete|{reason}}}}}\n"
            if text.startswith("{{delete"):
                progress.write(f"Skipping {full_title}: already tagged")
                if log_csv:
                    with log_csv.open("a", newline="") as fh:
                        writer = csv.DictWriter(fh, fieldnames=["title", "status", "reason"])
                        writer.writerow({"title": full_title, "status": "skipped", "reason": "already tagged"})
                progress.update(1)
                continue
            new_text = tag + text
            if apply:
                page.save(new_text, summary="Tagging page for deletion (author request)")
                tagged += 1
                if log_csv:
                    with log_csv.open("a", newline="") as fh:
                        writer = csv.DictWriter(fh, fieldnames=["title", "status", "reason"])
                        writer.writerow({"title": full_title, "status": "tagged", "reason": reason})
            else:
                progress.write(f"Dry-run {full_title}: would tag for deletion")
                tagged += 1
                if log_csv:
                    with log_csv.open("a", newline="") as fh:
                        writer = csv.DictWriter(fh, fieldnames=["title", "status", "reason"])
                        writer.writerow({"title": full_title, "status": "dry-run", "reason": reason})
        except Exception as exc:
            errors += 1
            progress.write(f"Error on {full_title}: {exc}")
            logging.exception("Error tagging %s", full_title)
            if log_csv:
                with log_csv.open("a", newline="") as fh:
                    writer = csv.DictWriter(fh, fieldnames=["title", "status", "reason"])
                    writer.writerow({"title": full_title, "status": "error", "reason": str(exc)})
        progress.update(1)
    progress.close()
    client.cleanup()
    print(f"Done. Processed: {len(titles)}, tagged/dry-run: {tagged}, errors: {errors}, apply={apply}")


if __name__ == "__main__":
    app()
