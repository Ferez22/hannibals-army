# MAIN CONFIG FILE - BACKBONE OR YOUR APP

APP_NAME = "Hannibal's Army"
MASTER_MODEL = "llama3:8b"

import yaml
DIGITAL_TWIN = yaml.safe_load(open("digital-twin-config.yml"))
