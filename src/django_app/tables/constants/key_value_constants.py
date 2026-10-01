import re

MAX_TABLE_NAME_LENGTH = 255
MAX_KEY_LENGTH = 512
MAX_VALUE_BYTES = 256 * 1024
VALUE_PREVIEW_CHARS = 200
MAX_KEYS_PER_REQUEST = 500
# Mirrors KEY_PATTERN in crew key_value_node.py and KEY_VALUE_KEY_PATTERN in the frontend.
# Always `fullmatch`: `$` also matches before a trailing newline.
KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
KEY_RULE = (
    "use only letters, digits and _, don't start with a digit, "
    f"and keep it to at most {MAX_KEY_LENGTH} characters"
)
