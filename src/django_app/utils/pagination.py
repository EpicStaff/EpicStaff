from rest_framework.pagination import LimitOffsetPagination


class DefaultLimitOffsetPagination(LimitOffsetPagination):
    """Project-wide `?limit=`/`?offset=` paging with a capped `?limit=`.

    Stock DRF leaves `max_limit` unset, so one request could force a worker to load and
    serialise a whole table. A larger `?limit=` is clamped to the cap and `next` links
    to the rest. The cap stays at 1000 because the frontend's "load all" calls request
    exactly that; a lower one would silently truncate them.
    """

    max_limit = 1000
