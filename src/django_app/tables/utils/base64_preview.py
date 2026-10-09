import json

# Enough to show that a file is there; SSE clients read the file itself from the API.
BASE64_PREVIEW_LENGTH = 50


def trim_base64_file_data(data):
    """Return a copy of ``data`` with every ``base64_data`` string cut to a preview."""
    if isinstance(data, dict):
        return {
            key: value[:BASE64_PREVIEW_LENGTH]
            if key == "base64_data" and isinstance(value, str)
            else trim_base64_file_data(value)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [trim_base64_file_data(item) for item in data]
    return data


def trim_base64_file_data_in_json(payload: str) -> str:
    """Return the JSON ``payload`` with its base64 file data cut to a preview.

    A payload without any is returned as it is, without being parsed.
    """
    if '"base64_data"' not in payload:
        return payload
    return json.dumps(trim_base64_file_data(json.loads(payload)))
