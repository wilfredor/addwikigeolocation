import os
import time
import requests
from GPSPhoto import gpsphoto
import math
import pyexiv2
import fractions
from PIL import Image
from PIL.ExifTags import TAGS
import sys


def to_deg(value, loc):
    if value < 0:
        loc_value = loc[0]
    elif value > 0:
        loc_value = loc[1]
    else:
        loc_value = ""
    abs_value = abs(value)
    deg = int(abs_value)
    t1 = (abs_value - deg) * 60
    min = int(t1)
    sec = round((t1 - min) * 60, 5)
    return (deg, min, sec, loc_value)


def set_gps_location(file_name, lat, lng):
    """Adds GPS position as EXIF metadata

    Keyword arguments:
    file_name -- image file
    lat -- latitude (as float)
    lng -- longitude (as float)

    """
    lat_deg = to_deg(lat, ["S", "N"])
    lng_deg = to_deg(lng, ["W", "E"])

    print
    lat_deg
    print
    lng_deg

    # convert decimal coordinates into degrees, munutes and seconds
    exiv_lat = (pyexiv2.Rational(lat_deg[0] * 60 + lat_deg[1], 60), pyexiv2.Rational(lat_deg[2] * 100, 6000),
                pyexiv2.Rational(0, 1))
    exiv_lng = (pyexiv2.Rational(lng_deg[0] * 60 + lng_deg[1], 60), pyexiv2.Rational(lng_deg[2] * 100, 6000),
                pyexiv2.Rational(0, 1))

    exiv_image = pyexiv2.Image(file_name)
    exiv_image.readMetadata()
    exif_keys = exiv_image.exifKeys()

    exiv_image["Exif.GPSInfo.GPSLatitude"] = exiv_lat
    exiv_image["Exif.GPSInfo.GPSLatitudeRef"] = lat_deg[3]
    exiv_image["Exif.GPSInfo.GPSLongitude"] = exiv_lng
    exiv_image["Exif.GPSInfo.GPSLongitudeRef"] = lng_deg[3]
    exiv_image["Exif.Image.GPSTag"] = 654
    exiv_image["Exif.GPSInfo.GPSMapDatum"] = "WGS-84"
    exiv_image["Exif.GPSInfo.GPSVersionID"] = '2 0 0 0'

    exiv_image.writeMetadata()

class ConfigConnection:

    def __init__(self, login, password):
        self._url = "https://commons.wikimedia.org/w/api.php"
        self._filename = None
        self._login = login
        self._password = password
        # Obtain a login token
        params = {
            'action': "query",
            'meta': "tokens",
            'type': "login",
            'format': "json"
        }
        self._s = requests.Session()
        r = self._s.get(url=self._url, params=params)
        data = r.json()
        self._login_token = data['query']['tokens']['logintoken']
        params = {
            'action': "login",
            'lgname': self._login,
            'lgpassword': self._password,
            'lgtoken': self._login_token,
            'format': "json"
        }
        r = self._s.post(self._url, data=params)

        # Obtain a CSRF token
        params = {
            "action": "query",
            "meta": "tokens",
            "format": "json"
        }
        r = self._s.get(url=self._url, params=params)
        data = r.json()
        self._csrf_token = data["query"]["tokens"]["csrftoken"]

        self._info = None
        self._metadata = None
        self._extmetadata = None

        self._METADATA_TYPE = 'metadata'
        self._EXTMETADATA_TYPE = 'extmetadata'

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
                'action': "query",
                'lgname': self._login,
                'lgpassword': self._password,
                'lgtoken': self._login_token,
                'format': "json",
                "list": "allimages",
                "aifrom": self._filename,
                "aito": self._filename
            }

            r = self._s.post(self._url, data=params)
            if r:
                data = r.json()
                images = data["query"]["allimages"]
                for img in images:
                    if img['name'] is not None:
                        return img
        return None

    def download_file_new(self):
        if os.path.isfile(self._filename):
            os.remove(self._filename)
        r = requests.get(self._info['url'], stream=True)
        bufsize = 1024
        with open(self._filename, 'wb', buffering=bufsize) as f:
            f.write(r.content)

    def _get_metadata_gps(self):
        return self._get_image_location_gps(self._METADATA_TYPE)

    def _get_extmetadata_gps(self):
        return self._get_image_location_gps(self._EXTMETADATA_TYPE)

    def _get_image_location_gps(self, metatype):
        start_of_end_point_str = self._url + '/?action=query&titles=File:'
        end_of_end_point_str = '&prop=imageinfo&iiprop=user' \
                               '|userid|canonicaltitle|url|'+metatype+'&format=json'
        request_url = start_of_end_point_str + self._filename + end_of_end_point_str
        result = requests.get(request_url)
        result = result.json()
        page_id = next(iter(result['query']['pages']))
        image_info = self._gps_info(result['query']['pages'][page_id], metatype)
        return image_info

    @staticmethod
    def _get_lat_lon_gps(gpsname, json_image_details):
        lat_lon = [image['value'] for image in json_image_details if image is not None and image['name'] == gpsname]
        if lat_lon:
            float(lat_lon[0])
        return None

    @staticmethod
    def _valid_json(image_info, metatype):
        if "imageinfo" in image_info:
            if image_info['imageinfo'][0]:
                if metatype in image_info['imageinfo'][0]:
                    if image_info['imageinfo'][0][metatype]:
                        return True
        return False

    def _gps_info(self, image_info, metatype):
        if self._valid_json(image_info, metatype):
            json_image_details = image_info['imageinfo'][0][metatype]
            if metatype == self._METADATA_TYPE:
                gps_latitude = self._get_lat_lon_gps("GPSLatitude", json_image_details)
                gps_longitude = self._get_lat_lon_gps("GPSLongitude", json_image_details)
                if gps_latitude and gps_longitude:
                    return [gps_latitude, gps_longitude]
            # Getting geolocation information from image metadata
            elif metatype == self._EXTMETADATA_TYPE:
                if "GPSLatitude" in json_image_details:
                    gps_latitude = float(json_image_details["GPSLatitude"]["value"])
                    gps_longitude = float(json_image_details['GPSLongitude']["value"])
                    return [gps_latitude, gps_longitude]
        return None

    def get_images_from_category(self, categoryname, params={}):
        start_of_end_point_str = self._url + '/?action=query&format=json&list=categorymembers&cmlimit=max&cmtitle=Category:'
        request_url = start_of_end_point_str + categoryname
        result = requests.get(request_url, params)
        result = result.json()
        image_info_list = result['query']['categorymembers']
        result_list = [image['title'].replace('File:', '') for image in image_info_list if image['title'].endswith(".jpg")]
        if "continue" in result:
            params = result["continue"]
            time.sleep(randrange(1))
            return result_list + self.get_images_from_category(categoryname, params)
        return result_list

    def can_set_metadata_location_gps(self):
        # If extmetadata is present and not metadata setted
        if self._extmetadata or self._metadata and not (self._extmetadata and self._metadata):
            return True
        return False
    def set_metadata_location_gps(self):
        if self.can_set_metadata_location_gps():
            time.sleep(randrange(10))
            print("External GPS", self._get_extmetadata_gps())
            gps_info = self._get_extmetadata_gps()
            set_gps_location(self._filename, gps_info[0], gps_info[1])
            '''
            info = gpsphoto.GPSInfo(self._get_extmetadata_gps())
            # Get local file downloaded
            photo = gpsphoto.GPSPhoto(self._filename)

            # Modify GPS Data locally
            photo.modGPSData(info, self._filename)
            # prevent overload the server
            '''
            time.sleep(randrange(10))

    def upload_to_commons(self):
        params = {
            "action": "upload",
            "filename": self._filename,
            "comment": "Adding geolocation",
            "format": "json",
            "token": self._csrf_token,
            "ignorewarnings": 1
        }

        file = {'file': (self._filename, open(self._filename, 'rb'), 'multipart/form-data')}
        # upload file to wikimedia commons
        r = self._s.post(self._url, files=file, data=params)
        data = r.json()
