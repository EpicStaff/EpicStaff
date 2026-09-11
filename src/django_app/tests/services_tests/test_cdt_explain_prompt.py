import pytest

from tables.services.cdt_explain.context import render_block, render_user_message
from tables.services.cdt_explain.system_prompt import build_system_prompt, section_key


class TestSystemPromptAssembly:
    def test_only_requested_sections_are_loaded(self):
        condition_only = build_system_prompt(["condition"])
        assert "Condition blocks" in condition_only
        assert "AI prompt blocks" not in condition_only
        assert "Assignment blocks" not in condition_only

    def test_pre_and_post_share_one_section(self):
        assert build_system_prompt(["pre_computation"]) == build_system_prompt(
            ["post_computation"]
        )
        assert build_system_prompt(["pre_computation", "post_computation"]) == (
            build_system_prompt(["pre_computation"])
        )

    def test_arrival_order_does_not_change_the_prompt(self):
        """Byte-identical prompts across arrival orders keep the prefix cacheable."""
        assert build_system_prompt(["prompt", "condition"]) == build_system_prompt(
            ["condition", "prompt"]
        )

    def test_size_is_flat_in_step_count(self):
        few = build_system_prompt(["condition", "manipulation"])
        many = build_system_prompt(["condition"] * 40 + ["manipulation"] * 12)
        assert few == many

    def test_unknown_block_type_is_rejected(self):
        with pytest.raises(ValueError, match="agent_evaluation"):
            build_system_prompt(["condition", "agent_evaluation"])

    def test_section_key_groups_computation_together(self):
        assert section_key("pre_computation") == section_key("post_computation")
        assert section_key("condition") != section_key("prompt")


def _condition(**overrides):
    block = {
        "id": "row-3:decision",
        "block": "condition",
        "rule_name": "Refund inside the return window",
        "order": 4,
        "enabled": True,
        "expression": '@intent == "refund"',
        "field_expressions": {},
        "continue_after_match": False,
        "route_code": None,
        "on_match": {"prompt": None, "sets_variables": False, "goes_to": None},
        "on_no_match": "next_rule",
    }
    block.update(overrides)
    return block


class TestConditionRendering:
    def test_field_expression_duplicating_the_expression_is_emitted_once(self):
        """The grid keeps the two in sync, so the same predicate usually arrives
        twice; describing it twice would read as two separate checks."""
        rendered = render_block(
            _condition(
                expression='@intent == "refund" and @urgency == "high"',
                field_expressions={"urgency": '== "high"'},
            ),
            1,
            1,
        )
        assert rendered.count("high") == 1
        assert "column conditions" not in rendered

    def test_field_expression_adding_a_new_clause_is_kept(self):
        rendered = render_block(
            _condition(
                expression='@intent == "refund"',
                field_expressions={"urgency": '== "high"'},
            ),
            1,
            1,
        )
        assert "column conditions" in rendered
        assert '@urgency == "high"' in rendered

    def test_bare_field_value_becomes_an_equality(self):
        rendered = render_block(
            _condition(expression=None, field_expressions={"status": '"start"'}), 1, 1
        )
        assert '@status == "start"' in rendered

    def test_no_conditions_at_all_is_stated_as_always_matching(self):
        rendered = render_block(
            _condition(expression=None, field_expressions={}), 1, 1
        )
        assert "always matches" in rendered

    def test_routing_row_notes_that_continue_has_no_effect(self):
        """Contract D2: a rule with a destination stops the table regardless."""
        rendered = render_block(
            _condition(
                continue_after_match=True,
                on_match={"prompt": None, "sets_variables": False, "goes_to": "refund_bot"},
            ),
            1,
            1,
        )
        assert "the continue setting has no effect" in rendered

    def test_non_routing_row_gets_no_such_note(self):
        rendered = render_block(_condition(continue_after_match=True), 1, 1)
        assert "no effect" not in rendered

    def test_unconnected_destination_falls_back_to_default(self):
        rendered = render_block(_condition(), 1, 1)
        assert "the table's default destination applies" in rendered

    def test_disabled_rule_is_flagged(self):
        rendered = render_block(_condition(enabled=False), 1, 1)
        assert "DISABLED" in rendered

    def test_route_code_is_labelled_as_non_routing(self):
        rendered = render_block(_condition(route_code="refund"), 1, 1)
        assert "does not affect routing" in rendered


class TestPromptRendering:
    def _prompt(self, **overrides):
        block = {
            "id": "row-3:prompt",
            "block": "prompt",
            "rule_name": "Refund inside the return window",
            "prompt_key": "draft_reply",
            "text": "Draft a reply.\n\nTicket: {message}",
            "result_variable": "reply_draft",
            "answer_schema": None,
            "model": "gpt-4o",
        }
        block.update(overrides)
        return block

    def test_result_mappings_are_described_as_post_response(self):
        """Contract D1: variable_mappings fan out of the answer, they are not inputs."""
        rendered = render_block(
            self._prompt(result_mappings={"detected_intent": "intent"}), 1, 1
        )
        assert "after the answer returns" in rendered
        assert "detected_intent ← intent" in rendered

    def test_legacy_fills_key_is_accepted_as_an_alias(self):
        """The frontend still sends `fills`; same value, wrong name."""
        rendered = render_block(self._prompt(fills={"detected_intent": "intent"}), 1, 1)
        assert "after the answer returns" in rendered

    def test_answer_schema_is_summarised_not_expanded(self):
        rendered = render_block(
            self._prompt(answer_schema={"type": "object", "properties": {"a": {}}}), 1, 1
        )
        assert "structured fields" in rendered
        assert "properties" not in rendered


class TestManipulationRendering:
    def test_empty_assignments_are_stated_explicitly(self):
        rendered = render_block(
            {
                "id": "row-3:manipulation",
                "block": "manipulation",
                "rule_name": "R",
                "assignments": None,
                "field_assignments": {},
            },
            1,
            1,
        )
        assert "changes no values" in rendered

    def test_both_assignment_forms_are_rendered(self):
        rendered = render_block(
            {
                "id": "row-3:manipulation",
                "block": "manipulation",
                "rule_name": "R",
                "assignments": '@queue = "refunds"',
                "field_assignments": {"route_reason": '"in window"'},
            },
            1,
            1,
        )
        assert '@queue = "refunds"' in rendered
        assert '@route_reason = "in window"' in rendered


class TestComputationRendering:
    def test_long_code_is_truncated_with_a_marker(self):
        rendered = render_block(
            {
                "id": "spine:pre-computation",
                "block": "pre_computation",
                "code": "x = 1\n" * 5000,
                "libraries": ["re"],
                "input_map": {"message": "variables.message"},
                "output_variable_path": "context",
            },
            1,
            1,
        )
        assert "truncated" in rendered
        assert len(rendered) < 4000

    def test_absent_output_path_is_stated(self):
        rendered = render_block(
            {
                "id": "exit:default:post",
                "block": "post_computation",
                "code": "pass",
                "libraries": [],
                "input_map": {},
                "output_variable_path": None,
            },
            1,
            1,
        )
        assert "not kept" in rendered


class TestUserMessage:
    def test_disabled_rules_are_listed_in_table_context(self):
        message = render_user_message(
            {
                "node_name": "t",
                "default_next_node": "a",
                "error_next_node": None,
                "default_model": "gpt-4o",
                "rules": [{"order": 1, "name": "R1", "enabled": False}],
            },
            [_condition()],
        )
        assert "DISABLED" in message
        assert "the flow ends here" in message  # error_next_node is None

    def test_every_block_is_rendered_and_counted(self):
        blocks = [_condition(id=f"row-{i}:decision") for i in range(3)]
        message = render_user_message({"node_name": "t", "rules": []}, blocks)
        for i in range(3):
            assert f"row-{i}:decision" in message
        assert "each of the 3 step(s)" in message
