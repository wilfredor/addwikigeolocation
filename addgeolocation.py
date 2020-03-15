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
if c.extmetadata() is not None:
    c.download_file()
    c.set_metadata_image_location_gps()
    # prevent overload the server
    time.sleep(randrange(10))
    c.upload_to_commons()
'''

'''
# Sample in category
t = PrettyTable()
t.field_names = ['filename', 'metadata', 'extmetadata']
t.align["City filename"] = "l"
images = tqdm(c.get_images_from_category("Quality_images_by_Wilfredor"))
for img in images:
    time.sleep(randrange(2))
    c.set_filename(img)
    images.set_description(img + " Processing...")
    if c.extmetadata() or c.metadata() and not(c.extmetadata() and c.metadata()):
        t.add_row([img, c.metadata(), c.extmetadata()])
print(t)
'''