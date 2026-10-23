"""In-memory stand-ins for the Weather sample's database stores, for tests of its routes.

Each keeps rows per organization, as the tables' row-level security does, so a route that
passes the wrong organization is caught. The real stores run against PostgreSQL in
`test_weather_sample_database.py`.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

SAVED_AT = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
# psycopg's pq.TransactionStatus values.
IDLE, IN_TRANSACTION = 0, 2


class FakeSavedPlaces:
    def __init__(self, places_module):
        self._places = places_module
        # id -> (org_id, created_by, SavedPlace)
        self.rows = {}
        # Each store_conditions call: (org_id, {place_id: PlaceConditions}).
        self.stored_conditions = []
        self._next_id = 1

    def seed(self, org_id, user_id, name, country, latitude=0.0, longitude=0.0, admin1=None, conditions=None):
        """Save a place at the end of the organization's list, as the store's add does.

        `conditions` takes what the database gives, a Decimal temperature and a timestamp in the
        session's time zone, and goes through the model as the store's rows do.
        """
        position = 1 + max((place.position for owner, _, place in self.rows.values() if owner == org_id), default=0)
        place = self._places.SavedPlace.model_validate(
            {
                "id": self._next_id,
                "name": name,
                "admin1": admin1,
                "country": country,
                "latitude": latitude,
                "longitude": longitude,
                "created_at": SAVED_AT,
                "position": position,
                "conditions": conditions,
            }
        )
        self.rows[place.id] = (org_id, user_id, place)
        self._next_id += 1
        return place

    async def list(self, org_id):
        places = [place for owner, _, place in self.rows.values() if owner == org_id]
        # The store's ORDER BY position, id.
        return sorted(places, key=lambda place: (place.position, place.id))

    async def store_conditions(self, org_id, conditions):
        self.stored_conditions.append((org_id, dict(conditions)))
        for place_id, value in conditions.items():
            # The store skips a place that is gone, or another organization's.
            if place_id in self.rows and self.rows[place_id][0] == org_id:
                owner, created_by, place = self.rows[place_id]
                self.rows[place_id] = (owner, created_by, place.model_copy(update={"conditions": value}))

    async def add(self, org_id, user_id, candidate):
        # The table's UNIQUE NULLS NOT DISTINCT (org_id, name, admin1, country).
        key = (candidate.name, candidate.admin1, candidate.country)
        if any(owner == org_id and (place.name, place.admin1, place.country) == key for owner, _, place in self.rows.values()):
            raise self._places.AlreadySaved
        return self.seed(
            org_id, user_id, candidate.name, candidate.country, candidate.latitude, candidate.longitude, candidate.admin1
        )

    async def remove(self, org_id, place_id):
        if place_id not in self.rows or self.rows[place_id][0] != org_id:
            return False
        del self.rows[place_id]
        return True


class FakeForecastRuns:
    def __init__(self):
        # (org_id, session_id) -> (user_id, city)
        self.runs = {}

    async def add(self, org_id, user_id, session_id, city):
        self.runs[(org_id, session_id)] = (user_id, city)

    async def started_by(self, org_id, user_id, session_id):
        return (org_id, session_id) in self.runs and self.runs[(org_id, session_id)][0] == user_id


class FakePopupRelay:
    def __init__(self):
        # (org_id, user_id, state) -> params
        self.results = {}
        self.lookups = 0

    async def put(self, org_id, user_id, state, params):
        self.results[(org_id, user_id, state)] = dict(params)

    async def take(self, org_id, user_id, state):
        self.lookups += 1
        return self.results.pop((org_id, user_id, state), None)


class _RecordingConnectionInfo:
    def __init__(self, connection):
        self._connection = connection
        self.user = "weather_app"

    @property
    def transaction_status(self):
        return IN_TRANSACTION if self._connection.depth else IDLE


class RecordingConnection:
    """A psycopg-shaped connection that records each statement with the transaction it ran in.

    `rowcounts(query)` gives the row count of each statement, and `rows(query)` the row its
    `fetchone()` returns (None by default); `error` makes every statement after the first (the
    transaction's own setting) raise it. Parameters are recorded as given: a tuple, or a dict
    of named ones.
    """

    def __init__(self, rowcounts=None, error=None, rows=None):
        self.statements = []
        self.depth = 0
        self.transactions = 0
        self.committed = []
        self.info = _RecordingConnectionInfo(self)
        self._rowcounts = rowcounts or (lambda query: 1)
        self._rows = rows or (lambda query: None)
        self._error = error

    @asynccontextmanager
    async def transaction(self):
        self.transactions += 1
        number = self.transactions
        self.depth += 1
        try:
            yield SimpleNamespace()
        finally:
            self.depth -= 1
        self.committed.append(number)

    async def execute(self, query, params=()):
        if self._error is not None and not query.startswith("SELECT pg_catalog.set_config"):
            raise self._error
        self.statements.append((self.transactions, query, dict(params) if isinstance(params, dict) else tuple(params)))
        row = self._rows(query)

        async def fetchone():
            return row

        return SimpleNamespace(rowcount=self._rowcounts(query), fetchone=fetchone)


class RecordingPool:
    """A connection pool that always lends out one `RecordingConnection`."""

    def __init__(self, connection):
        self.connection_lent = connection

    @asynccontextmanager
    async def connection(self):
        yield self.connection_lent
