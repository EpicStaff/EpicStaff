import time

import pytest
from application.commands import RunIndex
from application.sealed_secrets import open_sealed_secrets
from foundation.cryptographer import FernetRotatedCryptographer

CRYPTOGRAPHER = FernetRotatedCryptographer(
    "knowledge-tests-transport-key", hkdf_info=b"epicstaff.secrets.transport.test"
)


def run_index(
    extra_headers: dict[str, str] | None = None, connection: dict[str, str] | None = None
) -> RunIndex:
    return RunIndex(
        rag_id=1,
        document_ids=frozenset(),
        embedding_api_key=CRYPTOGRAPHER.encrypt("embedding-key"),
        embedding_extra_headers=extra_headers or {},
        embedding_connection=connection or {},
    )


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("epicstaff_secret({sealed})", "token-1"),
        ("epicstaff_secret(\n {sealed} \t)", "token-1"),
        ("a=epicstaff_secret({sealed});b=epicstaff_secret( {sealed} )", "a=token-1;b=token-1"),
        ("epicstaff_secret({sealed}", "epicstaff_secret({sealed}"),
        ("epicstaff_secret()", "epicstaff_secret()"),
        ("epicstaff_secret(   )", "epicstaff_secret(   )"),
        ("epicstaff_secret(epicstaff_secret({sealed})", "epicstaff_secret(token-1"),
        ("epicstaff_secret( epicstaff_secret({sealed})", "epicstaff_secret( token-1"),
    ],
    ids=[
        "plain",
        "padded-newline-tab",
        "two-markers",
        "unclosed",
        "empty",
        "blank",
        "unclosed-right-before-closed",
        "unclosed-space-before-closed",
    ],
)
def test_header_and_connection_markers_open_as_the_producer_writes_them(template, expected):
    sealed = CRYPTOGRAPHER.encrypt("token-1")
    value = template.format(sealed=sealed)

    opened = open_sealed_secrets(
        run_index(extra_headers={"X-Key": value}, connection={"aws_access_key_id": value}),
        CRYPTOGRAPHER,
    )

    assert opened.embedding_api_key == "embedding-key"
    assert opened.embedding_extra_headers == {"X-Key": expected.format(sealed=sealed)}
    assert opened.embedding_connection == {"aws_access_key_id": expected.format(sealed=sealed)}


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("epicstaff_secret(a" + " " * 50_000, id="name-then-spaces"),
        pytest.param("epicstaff_secret(" + " " * 50_000, id="spaces-only"),
        pytest.param("epicstaff_secret( " * 3_000, id="repeated-unclosed"),
    ],
)
def test_a_long_unclosed_marker_is_left_as_is_quickly(value):
    started = time.perf_counter()
    opened = open_sealed_secrets(run_index(extra_headers={"X-Key": value}), CRYPTOGRAPHER)

    assert time.perf_counter() - started < 1.0
    assert opened.embedding_extra_headers == {"X-Key": value}
