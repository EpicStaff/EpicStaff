import json

from conftest import load_tool_main

schema_validate_main = load_tool_main("schema_validate_tool").main


PERSON_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer", "minimum": 0},
    },
    "required": ["name", "age"],
}


class TestSchemaValidateToolPass:
    def test_valid_object_output_passes(self):
        result = schema_validate_main(
            output={"name": "Ada", "age": 30},
            schema=PERSON_SCHEMA,
        )

        assert result.startswith("PASS:")

    def test_valid_output_as_json_string_passes(self):
        result = schema_validate_main(
            output=json.dumps({"name": "Ada", "age": 30}),
            schema=PERSON_SCHEMA,
        )

        assert result.startswith("PASS:")
        assert "Normalized value" in result


class TestSchemaValidateToolFail:
    def test_missing_required_field_reports_violation(self):
        result = schema_validate_main(
            output={"name": "Ada"},
            schema=PERSON_SCHEMA,
        )

        assert result.startswith("FAIL:")
        assert "age" in result

    def test_wrong_type_reports_violation(self):
        result = schema_validate_main(
            output={"name": "Ada", "age": "thirty"},
            schema=PERSON_SCHEMA,
        )

        assert result.startswith("FAIL:")
        assert "age" in result
        assert "thirty" in result or "integer" in result

    def test_fail_message_instructs_retry(self):
        result = schema_validate_main(
            output={"name": "Ada"},
            schema=PERSON_SCHEMA,
        )

        assert "call this tool again" in result

    def test_max_attempts_hint_echoed_on_fail(self):
        result = schema_validate_main(
            output={"name": "Ada"},
            schema=PERSON_SCHEMA,
            max_attempts=3,
        )

        assert "max_attempts hint: 3" in result

    def test_multiple_errors_all_collected(self):
        result = schema_validate_main(
            output={"age": "thirty"},
            schema=PERSON_SCHEMA,
        )

        assert result.startswith("FAIL:")
        assert "name" in result
        assert "age" in result
        assert "2 violations" in result

    def test_truncation_announced_when_many_errors(self):
        big_schema = {
            "type": "object",
            "required": [f"field_{i}" for i in range(40)],
            "properties": {f"field_{i}": {"type": "string"} for i in range(40)},
        }

        result = schema_validate_main(output={}, schema=big_schema)

        assert result.startswith("FAIL:")
        assert "40 violations" in result
        assert "showing first 25 of 40" in result


class TestSchemaValidateToolDraftParsing:
    def test_malformed_draft_json_string_returns_readable_error(self):
        result = schema_validate_main(
            output="{not valid json",
            schema=PERSON_SCHEMA,
        )

        assert result.startswith("Error:")
        assert "not valid JSON" in result

    def test_array_output_against_array_schema(self):
        array_schema = {"type": "array", "items": {"type": "integer"}}

        result = schema_validate_main(output=[1, 2, 3], schema=array_schema)

        assert result.startswith("PASS:")

    def test_array_output_as_json_string(self):
        array_schema = {"type": "array", "items": {"type": "integer"}}

        result = schema_validate_main(output="[1, 2, 3]", schema=array_schema)

        assert result.startswith("PASS:")


class TestSchemaValidateToolSchemaValidation:
    def test_malformed_schema_returns_readable_error(self):
        bad_schema = {"type": "not_a_real_type"}

        result = schema_validate_main(output={"a": 1}, schema=bad_schema)

        assert result.startswith("Error:")
        assert "not a valid JSON Schema" in result

    def test_schema_not_a_dict_returns_readable_error(self):
        result = schema_validate_main(output={"a": 1}, schema="not-a-schema")

        assert result.startswith("Error:")
        assert "must be a JSON Schema object" in result


class TestSchemaValidateToolEdgeCases:
    def test_missing_output_argument_returns_error(self):
        result = schema_validate_main(schema=PERSON_SCHEMA)

        assert result.startswith("Error:")
        assert "output" in result

    def test_missing_schema_argument_returns_error(self):
        result = schema_validate_main(output={"name": "Ada", "age": 30})

        assert result.startswith("Error:")
        assert "schema" in result

    def test_never_raises_on_unexpected_input(self):
        # A schema value that passes the dict check but is nonsense enough to
        # stress the validator construction path -- must still return a
        # string, never raise.
        result = schema_validate_main(output={"a": 1}, schema={"type": 123})

        assert isinstance(result, str)
        assert result.startswith("Error:")
