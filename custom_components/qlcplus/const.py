"""Constants for the QLC+ integration."""

from datetime import timedelta

DOMAIN = "qlcplus"
PLATFORMS = ["switch", "number", "binary_sensor"]

CONF_SSL = "ssl"
CONF_PORT = "port"
CONF_HOST = "host"
CONF_EXPOSED_FUNCTIONS = "exposed_functions"
CONF_EXPOSED_TYPES = "exposed_types"
CONF_NAME_PREFIX = "name_prefix"

DEFAULT_PORT = 9999
DEFAULT_SCAN_INTERVAL = timedelta(seconds=15)
WEBSOCKET_PATH = "/qlcplusWS"
API_PREFIX = "QLC+API"
SERVICE_START_FUNCTION = "start_function"
SERVICE_STOP_FUNCTION = "stop_function"
SERVICE_SET_FUNCTION_STATE = "set_function_state"
SERVICE_REFRESH_FUNCTIONS = "refresh_functions"
ATTR_FUNCTION = "function"
ATTR_ENTITY_ID = "entity_id"
ATTR_STATE = "state"
