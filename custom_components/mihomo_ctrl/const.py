import logging

DOMAIN = "mihomo_ctrl"
LOGGER = logging.getLogger(__package__)

PLATFORMS = ["sensor", "select", "button"]

CONF_URL = "url"
CONF_TOKEN = "token"

# API Endpoints
ENDPOINT_TRAFFIC = "traffic"
ENDPOINT_CONNECTIONS = "connections"
ENDPOINT_PROXIES = "proxies"
ENDPOINT_CONFIG = "configs"
