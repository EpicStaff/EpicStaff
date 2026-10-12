import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from tables.models import Edge, PythonCode, PythonNode, Session, SessionCallback, StartNode
from tests.fixtures import *

SECRET = "x" * 32
ALLOWED = ["chat"]


@pytest.fixture
def session_data(graph):
    """A graph the start node leads out of; the shared fixture's lone start node is not runnable."""
    start = StartNode.objects.create(graph=graph, variables={})
    node = PythonNode.objects.create(
        graph=graph,
        node_name="first",
        python_code=PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n"),
    )
    Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=node.pk)
    return {"graph_id": graph.pk, "variables": {}}


def _system_client(api_client, env_api_key, default_org):
    raw_key, _ = env_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return api_client


@pytest.mark.django_db
@override_settings(SESSION_CALLBACK_ALLOWED_HOSTS=ALLOWED)
def test_system_key_registers_callback(api_client, env_api_key, default_org, redis_client_mock, session_data):
    client = _system_client(api_client, env_api_key, default_org)
    payload = {**session_data, "callback_url": "http://chat:8000/chat/internal/v1/session-callbacks", "callback_secret": SECRET}

    response = client.post(reverse("run-session"), payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    callback = SessionCallback.objects.get(session_id=response.data["session_id"])
    assert callback.url == payload["callback_url"]
    assert callback.secret == SECRET
    assert callback.status == SessionCallback.Status.REGISTERED


@pytest.mark.django_db
@override_settings(SESSION_CALLBACK_ALLOWED_HOSTS=ALLOWED)
def test_run_without_callback_creates_no_row(api_client, env_api_key, default_org, redis_client_mock, session_data):
    client = _system_client(api_client, env_api_key, default_org)

    response = client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert not SessionCallback.objects.filter(session_id=response.data["session_id"]).exists()


@pytest.mark.django_db
@override_settings(SESSION_CALLBACK_ALLOWED_HOSTS=ALLOWED)
def test_jwt_caller_cannot_register_callback(auth_client, redis_client_mock, session_data):
    payload = {**session_data, "callback_url": "http://chat:8000/cb", "callback_secret": SECRET}

    response = auth_client.post(reverse("run-session"), payload, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert Session.objects.count() == 0


@pytest.mark.django_db
@override_settings(SESSION_CALLBACK_ALLOWED_HOSTS=ALLOWED)
def test_user_key_cannot_register_callback(api_client, user_api_key, default_org, redis_client_mock, session_data):
    raw_key, _ = user_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(default_org.id))
    payload = {**session_data, "callback_url": "http://chat:8000/cb", "callback_secret": SECRET}

    response = api_client.post(reverse("run-session"), payload, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert Session.objects.count() == 0


@pytest.mark.django_db
@override_settings(SESSION_CALLBACK_ALLOWED_HOSTS=ALLOWED)
def test_user_key_of_superadmin_cannot_register_callback(api_client, superadmin_user, issue_api_key, default_org, redis_client_mock, session_data):
    raw_key, _ = issue_api_key(user=superadmin_user, name="superadmin-user-key")
    api_client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(default_org.id))
    payload = {**session_data, "callback_url": "http://chat:8000/cb", "callback_secret": SECRET}

    response = api_client.post(reverse("run-session"), payload, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert Session.objects.count() == 0


@pytest.mark.django_db
@override_settings(SESSION_CALLBACK_ALLOWED_HOSTS=ALLOWED)
@pytest.mark.parametrize(
    "url",
    [
        "http://evil.example/cb",
        "http://chat@evil.example/cb",
        "http://127.0.0.1:8000/cb",
        "ftp://chat/cb",
        "http://chat:abc/cb",
    ],
)
def test_host_not_on_allowlist_is_refused(api_client, env_api_key, default_org, redis_client_mock, session_data, url):
    client = _system_client(api_client, env_api_key, default_org)
    payload = {**session_data, "callback_url": url, "callback_secret": SECRET}

    response = client.post(reverse("run-session"), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "callback_url" in response.data
    assert Session.objects.count() == 0


@pytest.mark.django_db
@override_settings(SESSION_CALLBACK_ALLOWED_HOSTS=ALLOWED)
def test_allowed_host_with_port_is_accepted(api_client, env_api_key, default_org, redis_client_mock, session_data):
    client = _system_client(api_client, env_api_key, default_org)
    payload = {**session_data, "callback_url": "http://chat:8080/cb", "callback_secret": SECRET}

    response = client.post(reverse("run-session"), payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content


@pytest.mark.django_db
@override_settings(SESSION_CALLBACK_ALLOWED_HOSTS=ALLOWED)
def test_short_secret_is_refused(api_client, env_api_key, default_org, redis_client_mock, session_data):
    client = _system_client(api_client, env_api_key, default_org)
    payload = {**session_data, "callback_url": "http://chat:8000/cb", "callback_secret": "short"}

    response = client.post(reverse("run-session"), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "callback_secret" in response.data


@pytest.mark.django_db
@override_settings(SESSION_CALLBACK_ALLOWED_HOSTS=ALLOWED)
def test_url_without_secret_is_refused(api_client, env_api_key, default_org, redis_client_mock, session_data):
    client = _system_client(api_client, env_api_key, default_org)
    payload = {**session_data, "callback_url": "http://chat:8000/cb"}

    response = client.post(reverse("run-session"), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content


@pytest.mark.django_db
@override_settings(SESSION_CALLBACK_ALLOWED_HOSTS=ALLOWED)
def test_unreceived_publish_enqueues_error_callback(
    api_client, env_api_key, default_org, redis_client_mock, session_data
):
    redis_client_mock.publish.return_value = 1
    client = _system_client(api_client, env_api_key, default_org)
    payload = {**session_data, "callback_url": "http://chat/cb", "callback_secret": SECRET}

    response = client.post(reverse("run-session"), payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    callback = SessionCallback.objects.get(session_id=response.data["session_id"])
    assert callback.status == SessionCallback.Status.PENDING
    assert callback.payload["status"] == "error"
