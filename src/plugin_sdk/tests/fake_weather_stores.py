"""In-memory stand-ins for the Weather sample's database stores, for tests of its routes.

Each keeps rows per organization, as the tables' row-level security does, so a route that
passes the wrong organization is caught. The real stores run against PostgreSQL in
`test_weather_sample_database.py`.
"""

from datetime import UTC, datetime

SAVED_AT = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


class FakeSavedPlaces:
    def __init__(self, places_module):
        self._places = places_module
        # id -> (org_id, created_by, SavedPlace)
        self.rows = {}
        self._next_id = 1

    def seed(self, org_id, user_id, name, country, latitude=0.0, longitude=0.0, admin1=None):
        place = self._places.SavedPlace(
            id=self._next_id,
            name=name,
            admin1=admin1,
            country=country,
            latitude=latitude,
            longitude=longitude,
            created_at=SAVED_AT,
        )
        self.rows[place.id] = (org_id, user_id, place)
        self._next_id += 1
        return place

    async def list(self, org_id):
        places = [place for owner, _, place in self.rows.values() if owner == org_id]
        # The store's ORDER BY name, country, admin1 NULLS FIRST, id.
        return sorted(
            places, key=lambda place: (place.name, place.country, place.admin1 is not None, place.admin1 or "", place.id)
        )

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
