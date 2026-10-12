import pytest
from django.db import IntegrityError

from tables.models import SessionCallback
from tests.fixtures import *


@pytest.mark.django_db
def test_session_callback_defaults(session):
    callback = SessionCallback.objects.create(
        session=session, url="http://chat:8000/cb", secret="s" * 32
    )

    assert callback.status == SessionCallback.Status.REGISTERED
    assert callback.attempts == 0
    assert callback.payload == {}
    assert callback.next_attempt_at is None
    assert session.callback == callback


@pytest.mark.django_db
def test_one_callback_per_session(session):
    SessionCallback.objects.create(session=session, url="http://chat:8000/cb", secret="s" * 32)

    with pytest.raises(IntegrityError):
        SessionCallback.objects.create(session=session, url="http://chat:8000/cb", secret="t" * 32)
