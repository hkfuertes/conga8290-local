"""Domain + config keys for the cecotec_conga integration (icon: brands.home-assistant.io/cecotec_conga)."""
DOMAIN = "cecotec_conga"

# config flow / entry data
CONF_EMAIL = "email"
CONF_COUNTRY = "country_code"
CONF_HOST = "host"                # robot LAN IP
CONF_WAIT = "upload_wait"         # seconds to wait for cloud upload after get_both
# session + device fields stored in entry.data after login
CONF_SID = "sid"
CONF_ECODE = "ecode"
CONF_API_URL = "api_url"
CONF_PHONE_ID = "phone_device_id"
CONF_GID = "gid"
CONF_DEV_ID = "dev_id"            # cloud devId (== tuya device_id for this OEM)
CONF_DEVICE_ID = "device_id"      # LAN device id
CONF_LOCAL_KEY = "local_key"

ATTR_ROOMS = "rooms"
ATTR_PASSES = "passes"

PRODUCT_ID = "kofl9ubyyyfznpxw"   # Conga 8290 Immortal Ultra Power
TUYA_LOCAL_DEVICES = "custom_components/tuya_local/devices"
PROFILE_FILE = "tuya_local_profile.yaml"
