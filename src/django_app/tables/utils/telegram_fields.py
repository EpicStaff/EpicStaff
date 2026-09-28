import json
from functools import lru_cache

from django.conf import settings


@lru_cache(maxsize=1)
def load_telegram_trigger_fields():
    with open(settings.TELEGRAM_TRIGGER_FIELDS_PATH, encoding="utf-8") as f:
        return json.load(f)
