"""Limits on a Classification Decision Table node's stored `metadata["explanations"]`."""

MAX_STORED_EXPLANATIONS = 1000
# Above 255 on purpose: the frontend files a rule's explanation under
# `rule:name:<group_name>:<step>`, and `group_name` alone may be 255 characters.
MAX_STEP_KEY_LENGTH = 512
MAX_EXPLANATION_TEXT_LENGTH = 20_000
MAX_GENERATED_BY_LENGTH = 255
MAX_FINGERPRINT_LENGTH = 128
# The whole map as stored: compact JSON, UTF-8.
MAX_STORED_EXPLANATIONS_BYTES = 1024 * 1024
