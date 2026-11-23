# Every item carries all four keys, null when unused: clients read them without checking.
ITEM_KEYS = {"code", "detail", "attr", "context"}


def error_items(response) -> list[dict]:
    """The error items of an error answer, after checking the envelope every error answer has."""
    body = response.json()
    assert set(body) == {"type", "errors"}, body
    assert body["type"] == ("client_error" if response.status_code < 500 else "server_error"), body
    assert body["errors"], body
    assert all(set(item) == ITEM_KEYS for item in body["errors"]), body
    return body["errors"]


def first_error(response) -> dict:
    return error_items(response)[0]
