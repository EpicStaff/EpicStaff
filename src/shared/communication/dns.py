__all__ = ["build_dns"]


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
