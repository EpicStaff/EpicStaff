from rbac.authorship.checks import (
    MISCONFIGURED_OWNER_FIELD_CHECK_ID,
    check_last_edit_owner_fields,
)
from tables.models.graph_models import ClassificationConditionGroup


def test_every_declared_last_edit_owner_field_exists():
    assert check_last_edit_owner_fields(None) == []


def test_owner_field_check_reports_a_model_without_that_field(monkeypatch):
    monkeypatch.setattr(ClassificationConditionGroup, "last_edit_owner_field", "graph")

    errors = check_last_edit_owner_fields(None)

    assert [(error.obj, error.id) for error in errors] == [
        (ClassificationConditionGroup, MISCONFIGURED_OWNER_FIELD_CHECK_ID)
    ]
