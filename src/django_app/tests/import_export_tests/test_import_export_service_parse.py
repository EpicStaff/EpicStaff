"""
Tests for ViewSetImportExportService._parse_and_validate via inspect_entity().

All cases are DB-free: inspect_entity calls _parse_and_validate then InspectService.inspect,
neither of which touches the ORM.
"""

import io

import pytest
from rest_framework.exceptions import ValidationError

from tables.import_export.enums import EntityType
from tables.services.import_export_service import ViewSetImportExportService


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def service():
    """A ViewSetImportExportService for PythonCodeTool — no DB access required."""
    return ViewSetImportExportService(
        entity_type=EntityType.PYTHON_CODE_TOOL,
        export_prefix="python_code_tool",
        filename_attr="name",
    )


def _file(raw: bytes) -> io.BytesIO:
    return io.BytesIO(raw)


# ---------------------------------------------------------------------------
# _parse_and_validate guard cases (exercised via inspect_entity)
# ---------------------------------------------------------------------------


class TestParseAndValidateGuards:
    def test_malformed_json_raises_validation_error(self, service):
        with pytest.raises(ValidationError) as exc_info:
            service.inspect_entity(_file(b"{not json"))
        assert "Invalid JSON file" in str(exc_info.value.detail)

    def test_top_level_array_raises_validation_error(self, service):
        with pytest.raises(ValidationError) as exc_info:
            service.inspect_entity(_file(b"[]"))
        assert "expected a JSON object" in str(exc_info.value.detail)

    def test_bare_string_raises_validation_error(self, service):
        with pytest.raises(ValidationError) as exc_info:
            service.inspect_entity(_file(b'"hello"'))
        assert "expected a JSON object" in str(exc_info.value.detail)

    def test_bare_number_raises_validation_error(self, service):
        with pytest.raises(ValidationError) as exc_info:
            service.inspect_entity(_file(b"42"))
        assert "expected a JSON object" in str(exc_info.value.detail)

    def test_missing_main_entity_raises_validation_error(self, service):
        with pytest.raises(ValidationError) as exc_info:
            service.inspect_entity(_file(b"{}"))
        assert "main_entity" in str(exc_info.value.detail)

    def test_wrong_main_entity_raises_validation_error(self, service):
        payload = b'{"main_entity": "Flow", "version": 2, "Flow": []}'
        with pytest.raises(ValidationError) as exc_info:
            service.inspect_entity(_file(payload))
        detail = str(exc_info.value.detail)
        assert "Flow" in detail
        assert "PythonCodeTool" in detail

    def test_valid_payload_returns_review_items(self, service):
        payload = (
            b'{"main_entity": "PythonCodeTool", "version": 2, "PythonCodeTool": []}'
        )
        result = service.inspect_entity(_file(payload))
        assert result == {"review_items": []}
