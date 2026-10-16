from types import SimpleNamespace

import pytest
from presentation.rest.request_context import bearer_token


@pytest.mark.parametrize(
    ("header", "expected"),
    [("Bearer abc", "abc"), ("bearer abc", "abc"), ("Basic abc", None), ("Bearer", None), ("Bearer   ", None), (None, None)],
)
def test_bearer_token(header, expected):
    headers = {} if header is None else {"authorization": header}
    assert bearer_token(SimpleNamespace(headers=headers)) == expected
