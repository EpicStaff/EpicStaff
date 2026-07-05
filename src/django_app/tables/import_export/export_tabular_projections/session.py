import json

from tables.import_export.export_tabular_projections.base import TabularProjection


class SessionTabularProjection(TabularProjection):
    # TODO: if new node types are added we should update this list(at least for now).
    # consider moving message data dataclasses from crew/models/graph_models.py to src/shared/models/
    # so that CSV_FIELDS and csv_row_mapper can be auto-generated via dataclasses.fields()
    FIELDS = [
        "id",
        "session_id",
        "created_at",
        "name",
        "execution_order",
        "msg__type",
        "msg__crew_id",
        "msg__agent_id",
        "msg__task_id",
        "msg__text",
        "msg__thought",
        "msg__tool",
        "msg__tool_input",
        "msg__result",
        "msg__task_raw",
        "msg__error",
        "msg__task_description",
        "msg__task_expected_output",
        "msg__task_agent_name",
        "msg__llm_response",
        "msg__prompt_text",
        "msg__raw_response",
        "msg__parsed_result",
        "msg__group_name",
        "msg__condition_result",
        "msg__expression",
        "msg__input_json",
        "msg__output_json",
    ]

    def project(self, row: dict) -> dict:
        d = row.get("message_data") or {}
        mtype = d.get("message_type", "")

        def _json(val):
            return json.dumps(val) if val is not None else None

        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "created_at": row["created_at"],
            "name": row["name"],
            "execution_order": row["execution_order"],
            "msg__type": mtype,
            "msg__crew_id": d.get("crew_id"),
            "msg__agent_id": d.get("agent_id"),
            "msg__task_id": d.get("task_id"),
            "msg__text": d.get("text"),
            "msg__thought": d.get("thought"),
            "msg__tool": d.get("tool"),
            "msg__tool_input": d.get("tool_input"),
            "msg__result": d.get("result")
            if mtype in ("agent", "agent_finish")
            else None,
            "msg__task_raw": d.get("raw") if mtype == "task" else None,
            "msg__error": d.get("details") or d.get("error"),
            "msg__task_description": d.get("description"),
            "msg__task_expected_output": d.get("expected_output"),
            "msg__task_agent_name": d.get("agent") if mtype == "task" else None,
            "msg__llm_response": d.get("response"),
            "msg__prompt_text": d.get("prompt_text"),
            "msg__raw_response": d.get("raw_response"),
            "msg__parsed_result": _json(d.get("parsed_result")),
            "msg__group_name": d.get("group_name"),
            "msg__condition_result": str(d.get("result"))
            if mtype in ("condition_group", "condition_group_manipulation")
            else None,
            "msg__expression": d.get("expression"),
            "msg__input_json": _json(d.get("input")),
            "msg__output_json": _json(d.get("output")),
        }
