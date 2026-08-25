"""Shared CORS allow-list fallback logic.

Used by django_app (Django settings, module-level code), realtime, and
webhook (pydantic-settings BaseSettings properties) to compute the list of
trusted browser origins for credentialed CORS. See docs/security/cors.md.
"""


def resolve_cors_allowed_origins(
    frontend_base_url: str,
    domain_name: str,
    explicit: str = "",
) -> list[str]:
    frontend_base_url = frontend_base_url.rstrip("/")
    domain_name = domain_name.strip().strip('"')

    raw = explicit or ",".join(
        [frontend_base_url, f"http://{domain_name}", f"https://{domain_name}"]
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
