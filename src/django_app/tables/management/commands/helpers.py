import json
import os


def load_json_from_file(filepath):
    if not os.path.exists(filepath):
        return {}
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)
