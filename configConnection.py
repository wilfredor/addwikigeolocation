import os
import time
from random import randrange
import requests
from GPSPhoto import gpsphoto
import math
import fractions
from PIL import Image
from PIL.ExifTags import TAGS
import sys
from fractions import Fraction
import piexif
import struct
from typing import Any, Dict, Optional
from pathlib import Path
import mwclient
import mwclient


def decimal_to_dms(deg):
    """Converts decimal degrees to DMS format."""
    degrees = int(deg)
    minutes = int((deg - degrees) * 60)
    seconds = (deg - degrees - minutes / 60) * 3600
    return degrees, minutes, seconds


def set_gps_location(file_name, lat, lng):
    """Adds GPS coordinates as EXIF metadata to an image file using Pillow and piexif."""

    # Convert decimal coordinates into DMS format
    lat_deg = decimal_to_dms(lat)
    lng_deg = decimal_to_dms(lng)

    # Convert negative values to positive, handling N/S and E/W separately
    lat_sec = min(max(lat_deg[2], 0), 60)  # Ensure seconds are between 0 and 60
    lng_sec = min(max(lng_deg[2], 0), 60)  # Ensure seconds are between 0 and 60

    # Latitude and Longitude references (N/S, E/W)
    lat_ref = "N" if lat_deg[0] >= 0 else "S"
    lng_ref = "E" if lng_deg[0] >= 0 else "W"

    # Construct the GPS metadata with rational numbers (using absolute values for degrees, minutes, and seconds)
    gps_ifd = {
        piexif.GPSIFD.GPSLatitude: (
            (abs(lat_deg[0]), 1),  # Degrees as rational number (numerator, denominator)
            (lat_deg[1], 1),  # Minutes
            (
                int(lat_sec * 100),
                6000,
            ),  # Seconds as rational number (numerator, denominator)
        ),
        piexif.GPSIFD.GPSLatitudeRef: lat_ref,  # N/S
        piexif.GPSIFD.GPSLongitude: (
            (abs(lng_deg[0]), 1),  # Degrees as rational number (numerator, denominator)
            (lng_deg[1], 1),  # Minutes
            (
                int(lng_sec * 100),
                6000,
            ),  # Seconds as rational number (numerator, denominator)
        ),
        piexif.GPSIFD.GPSLongitudeRef: lng_ref,  # E/W
    }

    try:
        # Open image with Pillow
        image = Image.open(file_name)
        exif_dict = piexif.load(image.info.get("exif", b""))

        # Add GPS info to the EXIF dictionary
        exif_dict["GPS"] = gps_ifd

        # Dump the updated EXIF data and insert it into the image
        exif_bytes = piexif.dump(exif_dict)
        image.save(file_name, exif=exif_bytes)

        print(f"✅ GPS metadata added successfully to {file_name}")

    except struct.error as e:
        print(f"Error with EXIF data structure: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")


class ConfigConnection:
    def __init__(self, login, password):
        self._url = "https://commons.wikimedia.org/w/api.php"
        self._filename = None
        self._local_path: Optional[Path] = None
        self._download_dir = Path(".")
        self._login = login
        self._password = password
        self._s = requests.Session()
        self._s.headers.update(
            {
                "User-Agent": "AddGeoLocationBot/1.0 (https://github.com/wilfredor/addwikigeolocation; wilfredor@gmail.com)"
            }
        )
        self._site = mwclient.Site(
            host="commons.wikimedia.org",
            path="/w/",
            scheme="https",
            clients_useragent="AddGeoLocationBot/1.0 (https://github.com/wilfredor/addwikigeolocation; wilfredor@gmail.com)",
        )
        self._site.login(self._login, self._password)
        self._csrf_token = self._site.get_token("csrf")

        self._info = None
        self._metadata = None
        self._pagecoords = None

    def set_download_dir(self, path: str):
        self._download_dir = Path(path)
        self._download_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _strip_file_prefix(title: str) -> str:
        return title.replace("File:", "", 1) if title.startswith("File:") else title

    def _fetch_page_data(self, filename: str) -> Dict[str, Any]:
        title = f"File:{filename}"
        data = self._site.api(
            "query",
            prop="coordinates|imageinfo",
            iiprop="metadata|url",
            titles=title,
            format="json",
        )
        if not data or "query" not in data or "pages" not in data["query"]:
            return {}
        page = next(iter(data["query"]["pages"].values()))
        coords = None
        if "coordinates" in page:
            first = page["coordinates"][0]
            coords = [first.get("lat"), first.get("lon")]
        imageinfo = page.get("imageinfo", [])
        metadata = imageinfo[0].get("metadata", []) if imageinfo else []
        url = imageinfo[0].get("url") if imageinfo else None
        return {"coords": coords, "metadata": metadata, "url": url}

    def set_filename(self, value):
        self._filename = value
        safe_name = value.replace("/", "_")
        self._local_path = self._download_dir / safe_name
        page_data = self._fetch_page_data(value)
        self._metadata = page_data.get("metadata")
        self._pagecoords = page_data.get("coords")
        self._info = {"url": page_data.get("url")} if page_data.get("url") else None
        time.sleep(randrange(2))

    def metadata(self):
        return self._metadata

    def info(self):
        return self._info

    def local_path(self) -> Optional[Path]:
        return self._local_path

    def download_file_new(self):
        """Downloads a file from a URL and saves it with the specified filename."""

        # Check if the file information contains a valid URL
        if not self._info or "url" not in self._info:
            print("Error: No valid URL found in file information.")
            return

        file_url = self._info["url"]

        # Wikimedia requires a proper User-Agent
        headers = {
            "User-Agent": "AddGeoLocationBot/1.0 (https://github.com/wilfredor/addwikigeolocation; wilfredor@gmail.com)"
        }

        try:
            # If the file already exists, remove it before downloading
            if self._local_path and self._local_path.exists():
                self._local_path.unlink()

            print(f"Downloading from: {file_url}")

            # Perform the request with User-Agent
            with requests.get(file_url, headers=headers, stream=True, timeout=10) as r:
                r.raise_for_status()  # Raise an error if the request fails

                # Save the file in binary mode
                with open(self._local_path, "wb") as f:
                    for chunk in r.iter_content(
                        chunk_size=8192
                    ):  # Use a larger buffer (8KB)
                        f.write(chunk)

            print(f"Download completed: {self._local_path}")

        except requests.exceptions.RequestException as e:
            print(f"Error downloading the file: {e}")

    def _get_metadata_gps(self):
        if not self._metadata:
            return None
        gps_latitude = self._get_lat_lon_gps("GPSLatitude", self._metadata)
        gps_longitude = self._get_lat_lon_gps("GPSLongitude", self._metadata)
        if gps_latitude is not None and gps_longitude is not None:
            return [gps_latitude, gps_longitude]
        return None

    @staticmethod
    def _get_lat_lon_gps(gpsname, json_image_details):
        if not json_image_details:
            return None
        lat_lon = [
            image["value"]
            for image in json_image_details
            if image is not None and image["name"] == gpsname
        ]
        if not lat_lon:
            return None
        try:
            return float(lat_lon[0])
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _valid_coordinates(lat: float, lon: float) -> bool:
        return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180

    def _has_metadata_gps(self, metadata_block: list) -> bool:
        if not metadata_block:
            return False
        return (
            self._get_lat_lon_gps("GPSLatitude", metadata_block) is not None
            and self._get_lat_lon_gps("GPSLongitude", metadata_block) is not None
        )

    def get_user_uploads_with_gps(self, username: str, params: dict = {}) -> list:
        """Return uploads for a user with flags for page coords and EXIF GPS."""
        base_params = {
            "action": "query",
            "list": "usercontribs",
            "ucuser": username,
            "ucnamespace": "6",
            "uclimit": "max",
            "ucprop": "title",
        }
        base_params.update(params)
        results = []
        more_params = dict(base_params)
        total = 0
        while True:
            data = self._site.api(**more_params)
            if not data or "query" not in data or "usercontribs" not in data["query"]:
                break
            titles = [c["title"] for c in data["query"]["usercontribs"]]
            # Fetch metadata/coords in batches
            for i in range(0, len(titles), 50):
                batch = titles[i : i + 50]
                pages = self._site.api(
                    "query",
                    prop="imageinfo|coordinates",
                    iiprop="metadata|url",
                    titles="|".join(batch),
                    format="json",
                )
                if not pages or "query" not in pages or "pages" not in pages["query"]:
                    continue
                for page in pages["query"]["pages"].values():
                    title = self._strip_file_prefix(page.get("title", ""))
                    coords = page.get("coordinates")
                    has_coords = bool(coords)
                    imageinfo = page.get("imageinfo", [])
                    metadata_block = (
                        imageinfo[0].get("metadata", []) if imageinfo else []
                    )
                    has_exif_gps = self._has_metadata_gps(metadata_block)
                    results.append(
                        {
                            "title": title,
                            "has_coords": has_coords,
                            "has_exif_gps": has_exif_gps,
                        }
                    )
                    total += 1
                    if total % 500 == 0:
                        print(f" Scanned {total} uploads so far...")
            if "continue" not in data:
                break
            more_params.update(data["continue"])
            time.sleep(randrange(1))
        return results

    def can_set_metadata_location_gps(self):
        # Only write when GPS exists (page coords preferred, metadata fallback) and EXIF is missing.
        has_source = self._pagecoords or self._get_metadata_gps()
        return has_source and not self._get_metadata_gps()

    def set_metadata_location_gps(self):
        if self.can_set_metadata_location_gps():
            time.sleep(randrange(10))
            gps_info = self._pagecoords or self._get_metadata_gps()
            if not gps_info:
                print("No GPS info available to write for", self._filename)
                return
            if not self._valid_coordinates(gps_info[0], gps_info[1]):
                print("Invalid GPS info, skipping", self._filename, gps_info)
                return
            print("External GPS", gps_info)
            target_path = self._local_path or Path(self._filename)
            set_gps_location(target_path, gps_info[0], gps_info[1])
            """
            info = gpsphoto.GPSInfo(self._get_metadata_gps())
            # Get local file downloaded
            photo = gpsphoto.GPSPhoto(self._filename)

            # Modify GPS Data locally
            photo.modGPSData(info, self._filename)
            # prevent overload the server
            """
            time.sleep(randrange(10))

    def upload_to_commons(self):
        if not self._local_path:
            print("No local file to upload.")
            return
        with open(self._local_path, "rb") as fh:
            self._site.upload(
                fh,
                filename=self._filename,
                description=None,
                comment="Adding geolocation",
                ignore=True,
            )
