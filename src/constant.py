import os

from horangi import IS_AWS

LOG_LEVEL = os.environ.get('LOG_LEVEL', "INFO")

SQL_ECHO = False if IS_AWS else LOG_LEVEL == "DEBUG"

OUTBOUND_EVENT_BUS_NAME = os.environ.get("OUTBOUND_EVENT_BUS_NAME")
