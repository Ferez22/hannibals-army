import yaml
import os

# MAIN CONFIG FILE - BACKBONE OF YOUR APP

APP_NAME = "Hannibal's Army"
MASTER_MODEL = "gemma4:e2b"

DIGITAL_TWIN = yaml.safe_load(open("digital-twin-config.yml"))

# Company knowledge config — seed file, updated by agents as KG evolves
_company_config_path = "company-config.yml"
COMPANY = yaml.safe_load(open(_company_config_path)) if os.path.exists(_company_config_path) else {}

# Staleness thresholds (days) — DONNA uses these to flag stale entities
STALENESS_THRESHOLDS = {
    "person_role":      365,   # 12 months
    "team_structure":   180,   # 6 months
    "project_status":    90,   # 3 months
    "rule_policy":      180,   # 6 months
    "event":           None,   # never — historical record
}

# Gemma4 vision token budgets — image_parser picks based on task type
VISION_TOKEN_BUDGETS = {
    "caption":          70,    # simple captioning, fast
    "classification":  140,    # classify image type
    "document":        560,    # org charts, whiteboards, diagrams
    "ocr":            1120,    # dense text, small fonts, slides
}
