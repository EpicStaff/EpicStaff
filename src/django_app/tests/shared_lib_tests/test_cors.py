"""Pure function, no env/Django/DB — see docs/security/cors.md."""

from src.shared.cors import resolve_cors_allowed_origins


def test_explicit_overrides_fallback_and_strips_entries():
    result = resolve_cors_allowed_origins(
        frontend_base_url="http://localhost:4200",
        domain_name="localhost",
        explicit="https://a.com, , https://b.com,",
    )

    assert result == ["https://a.com", "https://b.com"]


def test_falls_back_to_frontend_and_domain_when_explicit_is_empty():
    result = resolve_cors_allowed_origins(
        frontend_base_url="http://localhost:4200",
        domain_name="example.com",
        explicit="",
    )

    assert result == [
        "http://localhost:4200",
        "http://example.com",
        "https://example.com",
    ]


def test_strips_trailing_slash_from_frontend_base_url_in_fallback():
    result = resolve_cors_allowed_origins(
        frontend_base_url="http://localhost:4200/",
        domain_name="example.com",
        explicit="",
    )

    assert result[0] == "http://localhost:4200"


def test_strips_quotes_and_whitespace_from_domain_name():
    # src/env.yaml's nginx default is the literal string `"localhost"`
    # (quotes included), so DOMAIN_NAME can arrive quoted.
    result = resolve_cors_allowed_origins(
        frontend_base_url="http://localhost:4200",
        domain_name=' "localhost" ',
        explicit="",
    )

    assert result == [
        "http://localhost:4200",
        "http://localhost",
        "https://localhost",
    ]
