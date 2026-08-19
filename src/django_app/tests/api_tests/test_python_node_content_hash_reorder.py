"""Regression tests for the content_hash CAS reorder fix on the single-node
REST path (``PythonNodeViewSet`` / ``ContentHashPreconditionMixin``), which
arms ``instance._expected_hash`` from raw ``request.data`` rather than
``validated_data`` — a second path hitting the same reorder bug.

Note: ``tests/api_tests/test_content_hash_precondition.py`` covers similar
ground but is entirely skipped due to an unrelated auth/RBAC setup gap
(verified: its failures are 403s, not content_hash related). This file uses
its own `force_authenticate` client override to avoid that gap.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.graph_models import PythonNode
from tests.fixtures import *  # noqa: F401,F403


@pytest.fixture
def auth_client(api_client, regular_user, default_org):
    """Override the global `auth_client`: PythonNodeViewSet needs
    `request.user` to be a real, authenticated, org-scoped user, but test
    settings clear `DEFAULT_AUTHENTICATION_CLASSES` so the JWT Bearer header
    from the global `auth_client` is never processed and `request.user`
    stays `AnonymousUser` (same gap documented in
    `tests/api_tests/bulk_save_test/conftest.py` and
    `tests/graph_collab/conftest.py`). `force_authenticate` bypasses
    authentication entirely.
    """
    api_client.force_authenticate(user=regular_user)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return api_client


@pytest.fixture
def python_node(graph, python_code) -> PythonNode:
    return PythonNode.objects.create(graph=graph, python_code=python_code)


def _detail_url(node_id: int) -> str:
    return reverse("pythonnode-detail", args=[node_id])


@pytest.mark.django_db
def test_patch_with_correct_hash_and_nested_code_change_succeeds(
    auth_client, python_node
):
    pre_edit_hash = python_node.content_hash
    pre_edit_nested_hash = python_node.python_code.content_hash
    pre_edit_python_code_id = python_node.python_code_id

    response = auth_client.patch(
        _detail_url(python_node.id),
        {
            "content_hash": pre_edit_hash,
            "python_code": {
                "code": "def main(): return 'patched'",
                "entrypoint": "main",
                "libraries": [],
                "global_kwargs": {},
                "content_hash": pre_edit_nested_hash,
            },
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    python_node.python_code.refresh_from_db()
    assert python_node.python_code.code == "def main(): return 'patched'"
    assert python_node.python_code_id == pre_edit_python_code_id


@pytest.mark.django_db
def test_patch_with_stale_hash_returns_409(auth_client, python_node):
    stale_hash = python_node.content_hash

    # Out-of-band write bypassing the model's save()/CAS entirely.
    PythonNode.objects.filter(pk=python_node.id).update(node_name="changed_out_of_band")

    response = auth_client.patch(
        _detail_url(python_node.id),
        {
            "content_hash": stale_hash,
            "python_code": {
                "code": "def main(): return 'should_not_persist'",
                "entrypoint": "main",
                "libraries": [],
                "global_kwargs": {},
            },
        },
        format="json",
    )

    assert response.status_code == status.HTTP_409_CONFLICT, response.content
    assert response.data["code"] == "content_hash_conflict"
    python_node.python_code.refresh_from_db()
    assert python_node.python_code.code != "def main(): return 'should_not_persist'"
