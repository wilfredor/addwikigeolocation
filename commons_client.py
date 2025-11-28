from __future__ import annotations

import os
import tempfile
import time
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from random import randrange
from typing import Any, Dict, Iterable, List, Optional, Tuple, Set

import mwclient
import piexif
import requests
from PIL import Image
from GPSPhoto import gpsphoto  # noqa: F401  # kept for reference/future use
from fractions import Fraction


def decimal_to_dms(deg: float):
    deg_abs = abs(deg)
    degrees = int(deg_abs)
    minutes_float = (deg_abs - degrees) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60
    return degrees, minutes, seconds


def set_gps_location(file_path: Path, lat: float, lng: float):
    """Adds GPS coordinates as EXIF metadata to an image file."""
    lat_deg = decimal_to_dms(lat)
    lng_deg = decimal_to_dms(lng)

    lat_sec = min(max(lat_deg[2], 0), 60)
    lng_sec = min(max(lng_deg[2], 0), 60)

    lat_ref = "N" if lat_deg[0] >= 0 else "S"
    lng_ref = "E" if lng_deg[0] >= 0 else "W"

    gps_ifd = {
        piexif.GPSIFD.GPSLatitude: (
            (abs(lat_deg[0]), 1),
            (abs(lat_deg[1]), 1),
            (int(abs(lat_sec) * 1000), 1000),
        ),
        piexif.GPSIFD.GPSLatitudeRef: lat_ref,
        piexif.GPSIFD.GPSLongitude: (
            (abs(lng_deg[0]), 1),
            (abs(lng_deg[1]), 1),
            (int(abs(lng_sec) * 1000), 1000),
        ),
        piexif.GPSIFD.GPSLongitudeRef: lng_ref,
    }

    image = Image.open(file_path)
    exif_dict = piexif.load(image.info.get("exif", b""))
    exif_dict["GPS"] = gps_ifd
    exif_bytes = piexif.dump(exif_dict)
    image.save(file_path, exif=exif_bytes)


def valid_coordinates(lat: Optional[float], lon: Optional[float]) -> bool:
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180


@dataclass
class UploadInfo:
    title: str
    has_coords: bool
    has_exif_gps: bool
    lat: Optional[float] = None
    lon: Optional[float] = None
    url: Optional[str] = None
    author: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Any) -> "UploadInfo":
        if isinstance(data, str):
            return UploadInfo(title=data, has_coords=False, has_exif_gps=False)
        return UploadInfo(
            title=data.get("title", ""),
            has_coords=data.get("has_coords", False),
            has_exif_gps=data.get("has_exif_gps", False),
            lat=data.get("lat"),
            lon=data.get("lon"),
            url=data.get("url"),
            author=data.get("author"),
        )


class CommonsClient:
    def __init__(self, login: str, password: str, download_dir: Optional[str] = None):
        self._login = login
        self._password = password
        self._site = mwclient.Site(
            host="commons.wikimedia.org",
            path="/w/",
            scheme="https",
            clients_useragent="AddGeoLocationBot/1.0 (https://github.com/wilfredor/addwikigeolocation; wilfredor@gmail.com)",
        )
        self._site.login(self._login, self._password)
        self._csrf_token = self._site.get_token("csrf")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "AddGeoLocationBot/1.0 (https://github.com/wilfredor/addwikigeolocation; wilfredor@gmail.com)"
            }
        )
        self._download_dir_ctx = None
        if download_dir:
            self._download_dir = Path(download_dir)
            self._download_dir.mkdir(parents=True, exist_ok=True)
        else:
            self._download_dir_ctx = tempfile.TemporaryDirectory()
            self._download_dir = Path(self._download_dir_ctx.name)
        self.download_dir = self._download_dir
        self._logger = logging.getLogger(__name__)

    def close(self):
        if self._download_dir_ctx:
            self._download_dir_ctx.cleanup()

    def _strip_file_prefix(self, title: str) -> str:
        return title.replace("File:", "", 1) if title.startswith("File:") else title

    def _has_metadata_gps(self, metadata_block: list) -> bool:
        if not metadata_block:
            return False
        return self._get_lat_lon_gps("GPSLatitude", metadata_block) is not None and self._get_lat_lon_gps(
            "GPSLongitude", metadata_block
        ) is not None

    @staticmethod
    def _get_lat_lon_gps(gpsname: str, json_image_details: Iterable[dict]) -> Optional[float]:
        lat_lon = [
            image["value"]
            for image in json_image_details
            if image is not None and isinstance(image, dict) and image.get("name") == gpsname
        ]
        if not lat_lon:
            return None
        try:
            return float(lat_lon[0])
        except (TypeError, ValueError):
            return None

    def _fetch_pages_batch(self, titles: Iterable[str]) -> List[UploadInfo]:
        pages = self._site.api(
            "query",
            prop="imageinfo|coordinates",
            iiprop="metadata|url|extmetadata",
            titles="|".join(titles),
            format="json",
        )
        results = []
        if not pages or "query" not in pages or "pages" not in pages["query"]:
            return results
        for page in pages["query"]["pages"].values():
            title = self._strip_file_prefix(page.get("title", ""))
            coords = page.get("coordinates")
            lat = coords[0].get("lat") if coords else None
            lon = coords[0].get("lon") if coords else None
            imageinfo = page.get("imageinfo", [])
            metadata_block = imageinfo[0].get("metadata", []) if imageinfo else []
            url = imageinfo[0].get("url") if imageinfo else None
            extmeta = imageinfo[0].get("extmetadata", {}) if imageinfo else {}
            author = extmeta.get("Artist", {}).get("value") or extmeta.get("Author", {}).get("value")
            has_coords = coords is not None
            has_exif_gps = self._has_metadata_gps(metadata_block)
            results.append(
                UploadInfo(
                    title=title,
                    has_coords=has_coords,
                    has_exif_gps=has_exif_gps,
                    lat=lat,
                    lon=lon,
                    url=url,
                    author=author,
                )
            )
        return results

    def list_uploads(
        self, username: str, cont_token: Optional[dict] = None, seen_titles: Optional[set] = None
    ) -> Tuple[List[UploadInfo], Optional[dict]]:
        base_params = {
            "action": "query",
            "list": "logevents",
            "letype": "upload",
            "leuser": username,
            "leprop": "title",
            "lelimit": "max",
        }
        if cont_token:
            base_params.update(cont_token)
        results: List[UploadInfo] = []
        seen = set(seen_titles) if seen_titles else set()
        total = 0
        while True:
            data = self._site.api(**base_params)
            if not data or "query" not in data or "logevents" not in data["query"]:
                return results, None
            titles = [ev.get("title") for ev in data["query"]["logevents"] if ev.get("title")]
            new_titles = [t for t in titles if t not in seen]
            seen.update(new_titles)
            for i in range(0, len(new_titles), 50):
                batch = new_titles[i : i + 50]
                batch_results = self._fetch_pages_batch(batch)
                results.extend(batch_results)
                total += len(batch_results)
                if total and total % 500 == 0:
                    print(f" Scanned {total} uploads so far...")
            if "continue" not in data:
                return results, None
            base_params.update(data["continue"])
            cont_token = data["continue"]
            time.sleep(randrange(1))

    def download_file(self, upload: UploadInfo) -> Optional[Path]:
        if not upload.url:
            return None
        local_path = self._download_dir / upload.title.replace("/", "_")
        if local_path.exists():
            local_path.unlink()
        try:
            with self._session.get(upload.url, stream=True, timeout=10) as r:
                r.raise_for_status()
                ctype = r.headers.get("Content-Type", "")
                if "jpeg" not in ctype.lower():
                    self._logger.warning("Skipping %s due to non-JPEG content-type: %s", upload.title, ctype)
                    return None
                with open(local_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            return local_path
        except requests.exceptions.RequestException as e:
            self._logger.error("Error downloading %s: %s", upload.title, e)
            return None

    def write_exif(self, upload: UploadInfo, local_path: Path):
        if not valid_coordinates(upload.lat, upload.lon):
            raise ValueError(f"Invalid coordinates for {upload.title}: {upload.lat}, {upload.lon}")
        set_gps_location(local_path, upload.lat, upload.lon)

    def upload_file(self, upload: UploadInfo, local_path: Path):
        with open(local_path, "rb") as fh:
            self._site.upload(
                fh,
                filename=upload.title,
                description=None,
                comment="Adding geolocation",
                ignore=True,
            )

    def cleanup(self):
        if self._download_dir_ctx:
            self._download_dir_ctx.cleanup()

    def cleanup_file(self, path: Path):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    def list_category_files(
        self, category: str, max_depth: int = 1, seen_titles: Optional[Set[str]] = None
    ) -> List[UploadInfo]:
        """List files in a category (recursing into subcats up to max_depth)."""
        queue = [(category, 0)]
        seen = set(seen_titles) if seen_titles else set()
        results: List[UploadInfo] = []
        while queue:
            cat, depth = queue.pop(0)
            cont_token = None
            while True:
                params = {
                    "action": "query",
                    "list": "categorymembers",
                    "cmtitle": f"Category:{cat}",
                    "cmtype": "file|subcat",
                    "cmlimit": "max",
                }
                if cont_token:
                    params.update(cont_token)
                data = self._site.api(**params)
                if not data or "query" not in data or "categorymembers" not in data["query"]:
                    break
                subcats = []
                titles = []
                for item in data["query"]["categorymembers"]:
                    title = item.get("title")
                    if item.get("ns") == 14 and depth < max_depth:
                        subcats.append(title.replace("Category:", "", 1))
                    elif item.get("ns") == 6 and title not in seen:
                        titles.append(title)
                        seen.add(title)
                for i in range(0, len(titles), 50):
                    batch = titles[i : i + 50]
                    results.extend(self._fetch_pages_batch(batch))
                for sc in subcats:
                    queue.append((sc, depth + 1))
                if "continue" not in data:
                    break
                cont_token = data["continue"]
                time.sleep(randrange(1))
        return results
