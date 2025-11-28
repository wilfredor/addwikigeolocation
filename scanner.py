from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from tempfile import NamedTemporaryFile
from datetime import datetime
import logging

from tqdm import tqdm

from commons_client import CommonsClient, UploadInfo


@dataclass
class ScanState:
    needs_exif: List[UploadInfo] = field(default_factory=list)
    needs_template: List[str] = field(default_factory=list)
    scan_continue: Optional[dict] = None

    def to_dict(self):
        return {
            "needs_exif": [u.to_dict() for u in self.needs_exif],
            "needs_template": list(self.needs_template),
            "scan_continue": self.scan_continue,
        }

    @staticmethod
    def from_dict(data: Optional[dict]) -> "ScanState":
        if not data:
            return ScanState()
        needs_exif = [
            UploadInfo.from_dict(item) for item in data.get("needs_exif", [])
        ]
        needs_template = data.get("needs_template", [])
        scan_continue = data.get("scan_continue")
        return ScanState(needs_exif=needs_exif, needs_template=needs_template, scan_continue=scan_continue)


def load_state(path: Path) -> ScanState:
    if path.exists():
        try:
            with path.open() as fh:
                return ScanState.from_dict(json.load(fh))
        except json.JSONDecodeError:
            ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            backup = path.with_suffix(path.suffix + f".corrupt.{ts}.bak")
            path.rename(backup)
            logging.warning("Corrupted state file moved to %s, starting fresh.", backup)
    return ScanState()


def save_state(path: Path, state: ScanState):
    tmp = NamedTemporaryFile("w", delete=False, dir=path.parent or Path("."))
    try:
        json.dump(state.to_dict(), tmp, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        os.replace(tmp.name, path)
    finally:
        try:
            tmp.close()
        except Exception:
            pass


def scan_user_uploads(
    client: CommonsClient,
    target_user: str,
    state: ScanState,
    state_path: Path,
    category: Optional[str] = None,
    max_depth: int = 1,
    author_filter: Optional[str] = None,
) -> ScanState:
    seen_titles = {u.title for u in state.needs_exif} | set(state.needs_template)
    cont = state.scan_continue
    # Clean any stale entries without coords before processing
    state.needs_exif = [u for u in state.needs_exif if u.has_coords]
    if state.needs_exif and state.needs_template and not cont:
        return state

    logging.info("Scanning uploads for %s...", target_user if not category else f"category {category}")
    progress = tqdm(total=None, unit="file", desc="Scanning", colour="cyan")
    while True:
        if category:
            uploads = client.list_category_files(category, max_depth=max_depth, seen_titles=seen_titles)
            cont = None
        else:
            uploads, cont = client.list_uploads(target_user, cont_token=cont, seen_titles=seen_titles)
        progress.update(len(uploads))
        for upload in uploads:
            if not upload.title.lower().endswith((".jpg", ".jpeg")):
                continue
            if author_filter and upload.author and author_filter.lower() not in upload.author.lower():
                continue
            if upload.has_coords and not upload.has_exif_gps:
                state.needs_exif.append(upload)
            elif upload.has_exif_gps and not upload.has_coords:
                state.needs_template.append(upload.title)
            seen_titles.add(upload.title)
        state.scan_continue = cont
        save_state(state_path, state)
        if not cont or not uploads:
            break
        time.sleep(1)
    progress.close()

    logging.info(
        "Scan complete. Found %s uploads (needs_exif=%s, needs_template=%s).",
        len(state.needs_exif) + len(state.needs_template),
        len(state.needs_exif),
        len(state.needs_template),
    )
    return state
