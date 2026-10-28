import time

from django.core.cache import cache

WINDOW_SECONDS = 60
MAX_CLIENT_ADDRESS_LENGTH = 64


class PublicRateLimiter:
    """Counts requests to a public path in fixed one-minute windows, per client address.

    The counters live in Django's cache (Redis), so every Django worker shares them. A
    window starts on the minute, so a client may get up to twice the limit across a window
    boundary.
    """

    def allow(self, identifier: str, rule_index: int, client_address: str, limit: int) -> bool:
        """Count this request; return False once the window holds more than `limit` of them."""
        window = int(time.time() // WINDOW_SECONDS)
        address = (client_address or "unknown")[:MAX_CLIENT_ADDRESS_LENGTH]
        key = f"plugins:gateway:public-rate:{identifier}:{rule_index}:{address}:{window}"
        # The key outlives its window a little, so a request at the boundary never revives it.
        cache.add(key, 0, timeout=WINDOW_SECONDS * 2)
        try:
            count = cache.incr(key)
        except ValueError:
            # Evicted between add and incr: this request starts the window again.
            cache.add(key, 1, timeout=WINDOW_SECONDS * 2)
            count = 1
        return count <= limit
