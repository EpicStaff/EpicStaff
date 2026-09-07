import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from tables.models.rbac_models import OrganizationUser
from tables.services.rbac.first_setup_service import FirstSetupService
from tables.services.rbac.rbac_exceptions import SetupAlreadyCompletedError


# `transaction=True` truncates every table at teardown, including the built-in
# Roles seeded once per session. This test does not repair that itself — it
# cannot, because pytest-django's transactional helper tears down after any
# fixture this test could request. The `heal_builtin_roles` autouse fixture in
# tests/conftest.py re-seeds at the start of the next database test instead.
@pytest.mark.django_db(transaction=True)
def test_concurrent_first_setup_creates_exactly_one_superadmin():
    """Security review finding #43: without the advisory lock both callers
    pass the `exists()` guard and two superadmins are created."""
    barrier = threading.Barrier(2, timeout=15)

    def attempt(email):
        barrier.wait()
        try:
            FirstSetupService().setup(email=email, password="StrongPass123!")
            return "created"
        except SetupAlreadyCompletedError:
            return "rejected"
        finally:
            # Each thread holds its own connection; close it so the test
            # database can be torn down.
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(attempt, ["a@example.com", "b@example.com"]))

    assert results == ["created", "rejected"]
    assert get_user_model().objects.count() == 1
    assert OrganizationUser.objects.count() == 1
