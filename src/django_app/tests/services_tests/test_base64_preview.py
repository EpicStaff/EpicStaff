import json

from tables.utils.base64_preview import (
    BASE64_PREVIEW_LENGTH,
    trim_base64_file_data,
    trim_base64_file_data_in_json,
)


def test_every_base64_string_is_cut_to_a_preview_wherever_it_is_nested():
    long_data = "C" * (BASE64_PREVIEW_LENGTH * 4)
    data = {
        "base64_data": long_data,
        "files": [{"name": "a.png", "base64_data": long_data}, "plain text"],
        "nested": {"deeper": {"base64_data": "short"}},
        "count": 3,
    }

    trimmed = trim_base64_file_data(data)

    assert trimmed == {
        "base64_data": long_data[:BASE64_PREVIEW_LENGTH],
        "files": [{"name": "a.png", "base64_data": long_data[:BASE64_PREVIEW_LENGTH]}, "plain text"],
        "nested": {"deeper": {"base64_data": "short"}},
        "count": 3,
    }
    assert data["base64_data"] == long_data


def test_json_without_file_data_is_returned_as_it_is():
    # Compact separators: parsing and encoding again would change the string.
    payload = '{"text":"no files","items":[1,2]}'

    assert trim_base64_file_data_in_json(payload) is payload


def test_json_with_file_data_is_returned_with_a_preview():
    payload = json.dumps({"files": [{"base64_data": "D" * 1000}]})

    assert json.loads(trim_base64_file_data_in_json(payload)) == {
        "files": [{"base64_data": "D" * BASE64_PREVIEW_LENGTH}]
    }
