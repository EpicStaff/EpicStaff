async def never_cancelled() -> bool:
    """Cancellation check for tests whose run is never withdrawn."""
    return False
