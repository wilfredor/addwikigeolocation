from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

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
        with path.open() as fh:
            return ScanState.from_dict(json.load(fh))
    return ScanState()


def save_state(path: Path, state: ScanState):
    with path.open("w") as fh:
        json.dump(state.to_dict(), fh, indent=2)


def scan_user_uploads(client: CommonsClient, target_user: str, state: ScanState, state_path: Path) -> ScanState:
    seen_titles = {u.title for u in state.needs_exif} | set(state.needs_template)
    cont = state.scan_continue
    # Clean any stale entries without coords before processing
    state.needs_exif = [u for u in state.needs_exif if u.has_coords]
    if state.needs_exif and state.needs_template and not cont:
        return state

    print(f"Scanning uploads for {target_user}...")
    while True:
        uploads, cont = client.list_uploads(target_user, cont_token=cont, seen_titles=seen_titles)
        print(f" Scan batch complete. Found {len(uploads)} items.")
        for upload in uploads:
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

    print(
        f"Scan complete. Found {len(state.needs_exif) + len(state.needs_template)} uploads "
        f"(needs_exif={len(state.needs_exif)}, needs_template={len(state.needs_template)})."
    )
    return state
