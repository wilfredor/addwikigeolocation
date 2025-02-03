from configConnection import ConfigConnection
import time
COUNT_NUMBER = 19
SLEEP_SECCONDS = 10
c = ConfigConnection(
    "<WIKIMEDIA_COMMONS_USER>",
    "<PASSWORD>",
    )

# Sample in category
edits_count = COUNT_NUMBER
images = c.get_images_from_category("Quality_images_by_Wilfredor")
for img in images:
    c.set_filename(img)
    # images.set_description(img + " Processing...")
    if c.can_set_metadata_location_gps():
        print("processing: ", c._filename)
        c.download_file_new()
        c.set_metadata_location_gps()
        '''
        c.upload_to_commons()
        '''
        edits_count -= 1
    if edits_count == 0:
        break
    time.sleep(SLEEP_SECCONDS)

