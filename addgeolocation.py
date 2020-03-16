from random import randrange
from tqdm import tqdm
from configConnection import ConfigConnection
import time
from prettytable import PrettyTable

c = ConfigConnection(
    "<BOT_USERNAME>",
    "<BOT_PASSWORD>"
    )

'''
# Sample of single image
c.set_filename("Basilica of Our Lady of the Rosary of Chiquinquirá (Venezuela) Exterior.jpg")
print(c.extmetadata())
print(c.metadata())

# There are geolocation information
# on the description page in wikimedia commons
c.set_metadata_location_gps()
c.upload_to_commons()

# Sample in category
t = PrettyTable()
t.field_names = ['filename', 'metadata', 'extmetadata']
t.align["filename"] = "l"
images = tqdm(c.get_images_from_category("Quality_images_by_Wilfredor"))
for img in images:
    c.set_filename(img)
    images.set_description(img + " Processing...")
    if c.can_set_metadata_location_gps():
        t.add_row([img, c.metadata(), c.extmetadata()])
print(t)
'''