"""Fork-only test runner: cla_sign.py with Drive replaced by a local folder."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import cla_sign  # noqa: E402

STORE = Path(os.environ.get("CLA_FAKE_DRIVE_DIR", ".cla-fake-drive"))


def get_or_create_version_folder(service, root_id, version):
    folder = STORE / f"v{version}"
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder)


def list_signature_filenames(service, folder_id):
    return {path.name for path in Path(folder_id).glob("*.json")}


def get_signature(service, folder_id, filename):
    path = Path(folder_id) / filename
    return json.loads(path.read_text()) if path.exists() else None


def put_signature(service, folder_id, filename, payload):
    (Path(folder_id) / filename).write_text(json.dumps(payload, indent=2))


cla_sign.drive_service = lambda: None
cla_sign.get_or_create_version_folder = get_or_create_version_folder
cla_sign.list_signature_filenames = list_signature_filenames
cla_sign.get_signature = get_signature
cla_sign.put_signature = put_signature

sys.exit(cla_sign.main())
