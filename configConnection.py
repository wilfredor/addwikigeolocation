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
        self._login = login
        self._password = password
        # Obtain a login token
        params = {
            "action": "query",
            "meta": "tokens",
            "type": "login",
            "format": "json",
        }
        self._s = requests.Session()
        r = self._s.get(url=self._url, params=params)
        data = r.json()
        self._login_token = data["query"]["tokens"]["logintoken"]
        params = {
            "action": "login",
            "lgname": self._login,
            "lgpassword": self._password,
            "lgtoken": self._login_token,
            "format": "json",
        }
        r = self._s.post(self._url, data=params)

        # Obtain a CSRF token
        params = {"action": "query", "meta": "tokens", "format": "json"}
        r = self._s.get(url=self._url, params=params)
        data = r.json()
        self._csrf_token = data["query"]["tokens"]["csrftoken"]

        self._info = None
        self._metadata = None
        self._extmetadata = None

        self._METADATA_TYPE = "metadata"
        self._EXTMETADATA_TYPE = "extmetadata"

    def set_filename(self, value):
        self._filename = value
        self._info = self._get_image_info()
        self._metadata = self._get_metadata_gps()
        self._extmetadata = self._get_extmetadata_gps()
        time.sleep(randrange(2))

    def metadata(self):
        return self._metadata

    def extmetadata(self):
        return self._extmetadata

    def info(self):
        return self._info

    def _get_image_info(self):
        if self._filename is not None:
            params = {
                "action": "query",
                "lgname": self._login,
                "lgpassword": self._password,
                "lgtoken": self._login_token,
                "format": "json",
                "list": "allimages",
                "aifrom": self._filename,
                "aito": self._filename,
            }

            r = self._s.post(self._url, data=params)
            if r:
                data = r.json()
                images = data["query"]["allimages"]
                for img in images:
                    if img["name"] is not None:
                        return img
        return None

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
            if os.path.exists(self._filename):
                os.remove(self._filename)

            print(f"Downloading from: {file_url}")

            # Perform the request with User-Agent
            with requests.get(file_url, headers=headers, stream=True, timeout=10) as r:
                r.raise_for_status()  # Raise an error if the request fails

                # Save the file in binary mode
                with open(self._filename, "wb") as f:
                    for chunk in r.iter_content(
                        chunk_size=8192
                    ):  # Use a larger buffer (8KB)
                        f.write(chunk)

            print(f"Download completed: {self._filename}")

        except requests.exceptions.RequestException as e:
            print(f"Error downloading the file: {e}")

    def _get_metadata_gps(self):
        return self._get_image_location_gps(self._METADATA_TYPE)

    def _get_extmetadata_gps(self):
        return self._get_image_location_gps(self._EXTMETADATA_TYPE)

    def _get_image_location_gps(self, metatype):
        start_of_end_point_str = self._url + "/?action=query&titles=File:"
        end_of_end_point_str = (
            "&prop=imageinfo&iiprop=user"
            "|userid|canonicaltitle|url|" + metatype + "&format=json"
        )
        request_url = start_of_end_point_str + self._filename + end_of_end_point_str
        result = requests.get(request_url)
        result = result.json()
        page_id = next(iter(result["query"]["pages"]))
        image_info = self._gps_info(result["query"]["pages"][page_id], metatype)
        return image_info

    @staticmethod
    def _get_lat_lon_gps(gpsname, json_image_details):
        lat_lon = [
            image["value"]
            for image in json_image_details
            if image is not None and image["name"] == gpsname
        ]
        if lat_lon:
            float(lat_lon[0])
        return None

    @staticmethod
    def _valid_json(image_info, metatype):
        if "imageinfo" in image_info:
            if image_info["imageinfo"][0]:
                if metatype in image_info["imageinfo"][0]:
                    if image_info["imageinfo"][0][metatype]:
                        return True
        return False

    def _gps_info(self, image_info, metatype):
        if self._valid_json(image_info, metatype):
            json_image_details = image_info["imageinfo"][0][metatype]
            if metatype == self._METADATA_TYPE:
                gps_latitude = self._get_lat_lon_gps("GPSLatitude", json_image_details)
                gps_longitude = self._get_lat_lon_gps(
                    "GPSLongitude", json_image_details
                )
                if gps_latitude and gps_longitude:
                    return [gps_latitude, gps_longitude]
            # Getting geolocation information from image metadata
            elif metatype == self._EXTMETADATA_TYPE:
                if "GPSLatitude" in json_image_details:
                    gps_latitude = float(json_image_details["GPSLatitude"]["value"])
                    gps_longitude = float(json_image_details["GPSLongitude"]["value"])
                    return [gps_latitude, gps_longitude]
        return None

    def get_images_from_category(self, categoryname, params={}):
        start_of_end_point_str = (
            self._url
            + "/?action=query&format=json&list=categorymembers&cmlimit=max&cmtitle=Category:"
        )
        request_url = start_of_end_point_str + categoryname
        result = requests.get(request_url, params)
        result = result.json()
        image_info_list = result["query"]["categorymembers"]
        result_list = [
            image["title"].replace("File:", "")
            for image in image_info_list
            if image["title"].endswith(".jpg")
        ]
        if "continue" in result:
            params = result["continue"]
            time.sleep(randrange(1))
            return result_list + self.get_images_from_category(categoryname, params)
        return result_list

    def can_set_metadata_location_gps(self):
        # If extmetadata is present and not metadata setted
        if (
            self._extmetadata
            or self._metadata
            and not (self._extmetadata and self._metadata)
        ):
            return True
        return False

    def set_metadata_location_gps(self):
        if self.can_set_metadata_location_gps():
            time.sleep(randrange(10))
            print("External GPS", self._get_extmetadata_gps())
            gps_info = self._get_extmetadata_gps()
            set_gps_location(self._filename, gps_info[0], gps_info[1])
            """
            info = gpsphoto.GPSInfo(self._get_extmetadata_gps())
            # Get local file downloaded
            photo = gpsphoto.GPSPhoto(self._filename)

            # Modify GPS Data locally
            photo.modGPSData(info, self._filename)
            # prevent overload the server
            """
            time.sleep(randrange(10))

    def upload_to_commons(self):
        params = {
            "action": "upload",
            "filename": self._filename,
            "comment": "Adding geolocation",
            "format": "json",
            "token": self._csrf_token,
            "ignorewarnings": 1,
        }

        file = {
            "file": (self._filename, open(self._filename, "rb"), "multipart/form-data")
        }
        # upload file to wikimedia commons
        r = self._s.post(self._url, files=file, data=params)
        data = r.json()