from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
import logging
import typer

from commons_client import CommonsClient
from processor import process_needs_exif
from scanner import load_state, save_state, scan_user_uploads, ScanState

app = typer.Typer(add_completion=False)


@app.command()
def main(
    target_user: str = typer.Option(None, "--target-user", help="Uploader to scan (defaults to login user)"),
    count: int = typer.Option(19, "--count", help="Max edits to perform"),
    sleep: float = typer.Option(10.0, "--sleep", help="Base sleep seconds"),
    max_edits_per_min: int = typer.Option(30, "--max-edits-per-min", help="Max edits per minute"),
    state_file: Path = typer.Option(Path("gps_scan.json"), "--state-file", help="Path to save scan results"),
    upload: bool = typer.Option(False, "--upload", help="Upload modified files back to Commons"),
    download_dir: Optional[Path] = typer.Option(None, "--download-dir", help="Directory to store downloads (defaults to temp)"),
    resume: bool = typer.Option(True, "--resume/--no-resume", help="Reuse existing scan file if present"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only list actions, do not modify files"),
    category: Optional[str] = typer.Option(None, "--category", help="Scan a category instead of uploader"),
    max_depth: int = typer.Option(1, "--max-depth", help="Category recursion depth"),
    author_filter: Optional[str] = typer.Option(None, "--author-filter", help="Filter by author name (defaults to target user)"),
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
):
    """Add GPS to EXIF using page coordinates for a user's uploads."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    target = target_user or commons_user
    author = author_filter or target

    client = CommonsClient(commons_user, commons_pass, download_dir=str(download_dir) if download_dir else None)
    state = load_state(state_file) if resume else ScanState()

    state = scan_user_uploads(client, target, state, state_file, category=category, max_depth=max_depth, author_filter=author)

    print(
        f"Uploads for {target}: {len(state.needs_exif)} need EXIF GPS, "
        f"{len(state.needs_template)} need page template."
    )
    if state.needs_template:
        print(f"Examples needing template (up to 5): {state.needs_template[:5]}")

    if dry_run:
        print("Dry run: exiting without modifications.")
        client.close()
        return

    updated, skipped_has_gps, skipped_no_gps, errors = process_needs_exif(
        client=client,
        state=state,
        state_path=state_file,
        count=count,
        base_sleep=sleep,
        max_edits_per_min=max_edits_per_min,
        upload=upload,
    )
    save_state(state_file, state)
    print(
        f"Finished. Updated: {updated}, skipped (has GPS): {skipped_has_gps}, "
        f"skipped (no GPS source): {skipped_no_gps}, errors: {errors}."
    )
    client.close()


if __name__ == "__main__":
    app()
