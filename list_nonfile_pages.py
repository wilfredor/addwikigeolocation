from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer
from tqdm import tqdm

from commons_client import CommonsClient

app = typer.Typer(add_completion=False)


@app.command()
def main(
    category: str = typer.Option(..., "--category", help="Category to scan (without 'Category:' prefix)"),
    max_depth: int = typer.Option(1, "--max-depth", help="Category recursion depth"),
    output: Path = typer.Option(Path("bad_pages.txt"), "--output", help="Output file with pages to delete"),
    log: bool = typer.Option(False, "--log", help="Print titles as they are found"),
):
    """
    Generate a list of existing pages whose title matches files in a category but without the 'File:' prefix.
    Requires COMMONS_USER / COMMONS_PASS in env for API access.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import os

    commons_user = os.getenv("COMMONS_USER")
    commons_pass = os.getenv("COMMONS_PASS")
    if not commons_user or not commons_pass:
        raise typer.Exit("COMMONS_USER and COMMONS_PASS must be set in env.")

    client = CommonsClient(commons_user, commons_pass)
    uploads = client.list_category_files(category, max_depth=max_depth)
    titles = []
    progress = tqdm(total=len(uploads), desc="Checking pages", unit="file", colour="cyan")
    for u in uploads:
        plain = u.title.replace("File:", "", 1)
        page = client._site.pages.get(plain)  # type: ignore
        if page and page.exists:
            titles.append(plain)
            if log:
                progress.write(f"Found page without File: {plain}")
        progress.update(1)
    progress.close()
    client.cleanup()

    with output.open("w") as fh:
        for t in titles:
            fh.write(t + "\n")

    print(f"Wrote {len(titles)} titles to {output}")


if __name__ == "__main__":
    app()
