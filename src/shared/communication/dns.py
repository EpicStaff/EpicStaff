import os

__all__ = ["build_dns", "redis_url"]


def build_dns(
    provider: str,
    host: str,
    port: int | str,
    db: str,
    user: str = "",
    password: str = "",
) -> str:
    user_part = f"{user}:{password}@" if user or password else ""
    return f"{provider}://{user_part}{host}:{port}/{db}"


def redis_url(prefix: str, provider: str) -> str:
    return build_dns(
        provider=provider,
        host=os.environ[f"{prefix}_HOST"],
        port=os.environ[f"{prefix}_PORT"],
        db=os.environ[f"{prefix}_DB"],
        user=os.environ.get(f"{prefix}_USER", ""),
        password=os.environ.get(f"{prefix}_PASSWORD", ""),
    )
