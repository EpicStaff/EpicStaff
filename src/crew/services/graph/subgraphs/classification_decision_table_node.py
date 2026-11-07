import itertools
import json
import re
from typing import Any

from foundation.utils.error_reference import log_with_reference
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamWriter
from loguru import logger
from pydantic import ValidationError
from services.graph.exceptions import InvalidStatePathError, NodeExecutionError, StopSession
from services.graph.subgraphs.decision_table_errors import (
    CONDITION_FAILURE_SOURCE,
    POST_COMPUTATION_SUBJECT,
    PRE_COMPUTATION_SUBJECT,
    ConditionFailure,
    DecisionTableError,
    UserCodePart,
    check_code_ran,
    condition_error,
    condition_subject,
    conditions_subject,
    manipulation_error,
    prompt_llm_error,
    unreadable_result_error,
    user_code_error,
)
from services.run_python_code_service import RunPythonCodeService
from src.crew.models.graph_models import (
    GraphMessage,
)
from src.crew.models.state import State
from src.crew.services.graph.custom_message_writer import CustomSessionMessageWriter
from src.crew.services.graph.events import StopEvent
from src.crew.services.graph.session_audit_provider import emit_session_audit_event
from src.shared.models import PythonCodeData
from src.shared.models.graph_nodes import (
    ClassificationConditionGroupData,
    ClassificationDecisionTableNodeData,
    PromptConfigData,
)
from src.shared.models.storage_scope import StorageCredentials
from src.shared.models.system_one import SYSTEM_ONE_PROMPT_KIND, SYSTEM_ONE_QUESTIONS_ADAPTER
from src.shared.public_error import PublicErrorMessage, build_public_error_message
from src.shared.system_one.adapter import SystemOneError, evaluate
from src.shared.system_one.json_llm import run_json_llm
from utils.set_output_variables import set_output_variables
from utils.state_path import split_state_path
from utils.template_render import render_template

# Expressions arrive as data and are compiled one at a time, so a syntax error in a
# row after the match never surfaces. Each row gets a fresh variable namespace;
# builtins, sys.modules and imported modules are shared by all rows of a batch.
# Lookup order matches the old per-row code, where the expression sat inside main():
# `variables`, then the identifier-named variables, then the sandbox module globals
# (json, os, sys, DotDict, get_secret, ...).
_EVALUATE_UNTIL_MATCH_CODE = (
    CONDITION_FAILURE_SOURCE
    + """
import types


def _to_ns(obj):
    if isinstance(obj, dict):
        return types.SimpleNamespace(**{k: _to_ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_to_ns(i) for i in obj]
    return obj


def _build_namespace(raw_variables):
    namespace = dict(globals())
    for key, value in raw_variables.items():
        if key.isidentifier():
            namespace[key] = _to_ns(value)
    namespace["variables"] = _to_ns(raw_variables)
    return namespace


def main(expressions, variables):
    results = []
    for expression in expressions:
        try:
            result = eval(
                compile(expression, "<condition>", "eval"), _build_namespace(variables)
            )
        # BaseException so that exit() in an expression is reported against its row.
        except BaseException as error:
            return {"results": results, "error": _condition_failure(error)}
        if not isinstance(result, bool):
            return {"results": results, "error": _NOT_BOOLEAN_FAILURE}
        results.append(result)
        if result:
            break
    return {"results": results, "error": None}
"""
)


class ClassificationDecisionTableNodeSubgraph:
    TYPE = "CLASSIFICATION_DECISION_TABLE"

    def __init__(
        self,
        session_id: int,
        node_data: ClassificationDecisionTableNodeData,
        graph_builder: StateGraph,
        stop_event: StopEvent,
        redis_service=None,
        custom_session_message_writer: CustomSessionMessageWriter | None = None,
        storage_credentials: StorageCredentials | None = None,
    ):
        self.node_data = node_data
        self._graph_builder = graph_builder
        self.session_id = session_id
        self.node_name = node_data.node_name
        self.stop_event = stop_event
        self.redis_service = redis_service
        self.custom_session_message_writer = (
            custom_session_message_writer or CustomSessionMessageWriter()
        )
        self.storage_credentials = storage_credentials

    async def _publish_message(self, graph_message: GraphMessage):
        """Add a GraphMessage directly to the graph message stream.
        Subgraph StreamWriter messages don't propagate to the parent graph's
        astream, so we write to Redis directly instead - and, since that
        also means _emit_session_audit_event's own interception point (the
        parent's astream loop) never sees these chunks either, dispatch to
        the audit pipeline explicitly here too, right alongside the primary
        write (the same encoded message, so both pipelines agree on the
        event's identity and content)."""
        if self.redis_service is None:
            return
        data = graph_message.to_payload()
        encoded_data = GraphMessage.encode_payload(data)
        await self.redis_service.aadd_graph_message(data["uuid"], encoded_data)
        try:
            emit_session_audit_event(encoded_data)
        except Exception as audit_exc:
            # Audit must never break the primary pipeline.
            logger.warning(f"Audit dispatch failed, dropping: {audit_exc}")

    @staticmethod
    def _resolve_path(path_expr: str, ctx: dict):
        """Safely resolve a dot/bracket path expression against a context dict.

        Supports:
          - dot access:    "variables.chat_id"
          - bracket access with dynamic key: "variables.messages[variables.index].text"
          - direct lookup: "session_id"

        No eval() is used.
        """

        # Tokenise into dot-segments and bracket-segments
        # e.g. "variables.messages[variables.index].text"
        #   → ["variables", "messages", "[variables.index]", "text"]
        tokens: list[str] = []
        for part in re.split(r"\.(?![^\[]*\])", path_expr):
            # Split bracket sub-expressions within each part
            sub = re.split(r"(\[[^\]]+\])", part)
            for s in sub:
                if s:
                    tokens.append(s)

        value = None
        for i, token in enumerate(tokens):
            if token.startswith("[") and token.endswith("]"):
                # Bracket access — resolve the inner expression recursively
                inner = token[1:-1]
                key = ClassificationDecisionTableNodeSubgraph._resolve_path(inner, ctx)
                value = value[key]
            elif i == 0:
                # First token — look up in context
                if token in ctx:
                    value = ctx[token]
                else:
                    raise KeyError(f"'{token}' not found in context")
            else:
                # Block dunder/underscore tokens: the author-controlled path
                # could otherwise reach Python internals (e.g. __globals__).
                if token.startswith("_"):
                    raise KeyError(f"'{token}' is not an allowed path segment")
                # Dot access — try getattr, then [] for dict-like objects
                try:
                    value = getattr(value, token)
                except AttributeError:
                    value = value[token]
        return value

    def _resolve_input_map(self, input_map: dict[str, str] | None, state: State) -> dict:
        """Resolve input_map path expressions against state, returning a flat dict of values."""
        if not input_map:
            return {}

        resolve_ctx: dict = {
            "variables": state["variables"],
            "system_variables": state.get("system_variables", {}),
            "session_id": self.session_id,
            "node_name": self.node_name,
        }

        resolved: dict = {}

        for local_name, path_expr in input_map.items():
            try:
                resolved[local_name] = self._resolve_path(path_expr, resolve_ctx)
            except Exception as e:
                logger.warning(f"Input map resolve failed for '{local_name}' = '{path_expr}': {e}")
                resolved[local_name] = None

        return resolved

    async def _execute_computation(
        self,
        python_code: "PythonCodeData | None",
        input_map: dict[str, str] | None,
        output_variable_path: str | None,
        state: State,
        subject: str,
    ) -> None:
        """Execute computation via sandboxed RunPythonCodeService.

        Raises:
            DecisionTableError: The code failed, or the sandbox couldn't run it.
        """
        if python_code is None or not python_code.code.strip():
            return

        # Rejected before the sandbox call, which would otherwise run for nothing.
        if output_variable_path:
            split_state_path(output_variable_path)

        inputs = self._resolve_input_map(input_map, state)

        result = await RunPythonCodeService(redis_service=self.redis_service).run_code(
            python_code_data=python_code,
            inputs=inputs,
            stop_event=self.stop_event,
            storage_credentials=self.storage_credentials,
        )

        check_code_ran(result, subject, session_id=self.session_id, node_name=self.node_name)
        if result.failure is not None:
            raise user_code_error(subject, result.failure)

        if output_variable_path:
            try:
                output = json.loads(result.result_data)
            except (TypeError, ValueError) as error:
                raise unreadable_result_error(subject, result.result_data) from error
            set_output_variables(
                state=state,
                output_variable_path=output_variable_path,
                output=output,
            )

    async def _execute_pre_computation(self, state: State) -> None:
        """Execute pre-computation via sandbox."""
        await self._execute_computation(
            python_code=self.node_data.pre_python_code,
            input_map=self.node_data.pre_input_map,
            output_variable_path=self.node_data.pre_output_variable_path,
            state=state,
            subject=PRE_COMPUTATION_SUBJECT,
        )

    async def _execute_post_computation(self, state: State) -> None:
        """Execute post-computation via sandbox."""
        await self._execute_computation(
            python_code=self.node_data.post_python_code,
            input_map=self.node_data.post_input_map,
            output_variable_path=self.node_data.post_output_variable_path,
            state=state,
            subject=POST_COMPUTATION_SUBJECT,
        )

    def _build_var_assignments(self, variable_keys: list[str]) -> str:
        """Generate explicit local variable assignments from state keys."""
        lines = []
        for key in variable_keys:
            if key.isidentifier():
                lines.append(f"    {key} = _to_ns(_raw.get('{key}'))")
        return "\n".join(lines)

    @staticmethod
    def _build_condition_expression(group: ClassificationConditionGroupData) -> str | None:
        """Combine a row's field_expressions and main expression into one expression.

        Field expression format:
          - Bare value: auto-wrapped as `field == value` (value must be valid Python,
            e.g. `"start"`, `True`, `42`)
          - Operator prefix: `> 5`, `!= "end"`, `in ("a", "b")` → prepended with field name
          - Full expression with operators: used as-is (e.g. `field > 0 and field < 10`)
        """
        parts = []
        _operator_prefixes = (
            "==",
            "!=",
            ">=",
            "<=",
            ">",
            "<",
            " in ",
            " not ",
        )
        if group.field_expressions:
            for field_name, field_expr in group.field_expressions.items():
                if field_expr and field_expr.strip():
                    expr = field_expr.strip()
                    if expr.startswith(_operator_prefixes) or expr.startswith(
                        ("in ", "not ", "is ")
                    ):
                        expr = f"{field_name} {expr}"
                    elif not any(
                        op in expr
                        for op in (
                            "==",
                            "!=",
                            ">=",
                            "<=",
                            ">",
                            "<",
                            " in ",
                            " not ",
                            " is ",
                            " and ",
                            " or ",
                        )
                    ):
                        expr = f"{field_name} == {expr}"
                    parts.append(f"({expr})")
        if group.expression and group.expression.strip():
            parts.append(f"({group.expression.strip()})")

        return " and ".join(parts) if parts else None

    async def _evaluate_until_match(
        self, expressions: list[str], state: State, subject: str
    ) -> tuple[list[bool], ConditionFailure | None]:
        """Evaluate row expressions in order, in one sandbox run, up to the first match.

        Only a matched row changes state, so every row up to the next match sees the
        same variables and can share one run. Evaluation stops at the first True or the
        first failing expression; later expressions are never compiled or run. The
        whole batch shares one SANDBOX_DEFAULT_EXECUTION_TIMEOUT.

        Args:
            subject: Names the evaluated rows in a message about the run itself.

        Returns:
            The result of each evaluated row, and why the row right after them (index
            `len(results)`) failed, if it did, else None.

        Raises:
            DecisionTableError: The sandbox run itself failed or returned an unreadable
                result.
        """
        result = await RunPythonCodeService(redis_service=self.redis_service).run_code(
            python_code_data=PythonCodeData(
                code=_EVALUATE_UNTIL_MATCH_CODE,
                entrypoint="main",
            ),
            inputs={
                "expressions": expressions,
                "variables": state["variables"].model_dump(),
            },
            stop_event=self.stop_event,
            storage_credentials=self.storage_credentials,
        )

        check_code_ran(result, subject, session_id=self.session_id, node_name=self.node_name)
        if result.failure is not None:
            # The evaluation reports the rows' own errors in its result, so this is the
            # sandbox stopping the code, e.g. at its time limit.
            raise DecisionTableError(f"{subject}: {result.failure.detail}")
        try:
            evaluation = json.loads(result.result_data)
            results = evaluation["results"]
            failure = ConditionFailure.from_result(evaluation["error"])
        except (TypeError, ValueError, KeyError) as error:
            raise unreadable_result_error(subject, result.result_data) from error
        if (
            not isinstance(results, list)
            or not all(isinstance(row_result, bool) for row_result in results)
            or len(results) + (failure is not None) > len(expressions)
            or (failure is None and not results)
        ):
            raise unreadable_result_error(subject, result.result_data)
        return results, failure

    @staticmethod
    def _manipulation_sources(
        group: ClassificationConditionGroupData,
    ) -> list[tuple[str, str, bool]]:
        """Return a row's manipulations in the order they run.

        Each is (label, code, shows_line_numbers): a field manipulation is one assignment
        the user wrote as an expression, the main manipulation is code with lines.
        """
        sources = []
        for var_name, var_expr in group.field_manipulations.items():
            if var_expr and var_expr.strip():
                variable_name = var_name.strip().removeprefix("variables.")
                sources.append(
                    (
                        f'manipulation of "{variable_name}"',
                        f"variables.{variable_name} = {var_expr.strip()}",
                        False,
                    )
                )
        if group.manipulation:
            sources.append(("manipulation code", group.manipulation, True))
        return sources

    async def _execute_manipulation(
        self, condition_name: str, sources: list[tuple[str, str, bool]], state: State
    ) -> None:
        """Execute manipulation code in sandbox. Updates state variables.

        Raises:
            DecisionTableError: The code failed, or the sandbox couldn't run it.
        """
        variables_dict = state["variables"].model_dump()

        var_assignments = self._build_var_assignments(list(variables_dict.keys()))

        code_prefix = f"""
import types

def _to_ns(obj):
    if isinstance(obj, dict):
        return types.SimpleNamespace(**{{k: _to_ns(v) for k, v in obj.items()}})
    if isinstance(obj, list):
        return [_to_ns(i) for i in obj]
    return obj

def _from_ns(obj):
    if isinstance(obj, types.SimpleNamespace):
        return {{k: _from_ns(v) for k, v in vars(obj).items()}}
    if isinstance(obj, list):
        return [_from_ns(i) for i in obj]
    return obj

def main(**kwargs) -> dict:
    _raw = kwargs.get("variables", {{}})
{var_assignments}
    variables = _to_ns(_raw)

"""
        code_suffix = """

    # Write back from namespace to dict
    return _from_ns(variables)
"""
        manipulation = "\n".join(source for _, source, _ in sources)
        code = code_prefix + self._indent_code(manipulation) + code_suffix
        parts = []
        first_line = code_prefix.count("\n") + 1
        for label, source, shows_line_numbers in sources:
            line_count = source.count("\n") + 1
            parts.append(UserCodePart(label, first_line, line_count, shows_line_numbers))
            first_line += line_count

        python_code_data = PythonCodeData(
            code=code,
            entrypoint="main",
        )

        variables_dict = state["variables"].model_dump()

        result = await RunPythonCodeService(redis_service=self.redis_service).run_code(
            python_code_data=python_code_data,
            inputs={"variables": variables_dict},
            stop_event=self.stop_event,
            storage_credentials=self.storage_credentials,
        )

        check_code_ran(
            result,
            condition_subject(condition_name),
            session_id=self.session_id,
            node_name=self.node_name,
        )
        if result.failure is not None:
            raise manipulation_error(condition_name, result.failure, parts)

        try:
            variables = json.loads(result.result_data)
        except (TypeError, ValueError) as error:
            raise unreadable_result_error(
                condition_subject(condition_name), result.result_data
            ) from error
        state["variables"].update(variables)

    def _render_prompt(self, prompt_text: str, variables: dict) -> str:
        """Render `{var_name}` placeholders; a prompt naming a missing variable is sent as written."""
        rendered = render_template(prompt_text, variables)
        if rendered.unrendered_reason:
            logger.warning(
                "Classification node '{}' prompt sent as written, no placeholder filled: {}",
                self.node_name,
                rendered.unrendered_reason,
            )
        if rendered.missing:
            return prompt_text
        return rendered.text

    def _store_prompt_result(
        self, prompt_config: PromptConfigData, result: Any, state: State
    ) -> str:
        """Store a prompt result under its result variable and apply variable_mappings.

        Returns the result variable name.
        """
        result_var = prompt_config.result_variable or "prompt_result"
        state["variables"].update({result_var: result})

        # Apply variable_mappings: extract specific fields from result into state variables
        if prompt_config.variable_mappings and isinstance(result, dict):
            for state_var, result_field in prompt_config.variable_mappings.items():
                if result_field in result:
                    state["variables"].update({state_var: result[result_field]})
                    logger.debug("Mapped result.{} -> variables.{}", result_field, state_var)
        return result_var

    async def _execute_system_one_prompt(
        self, prompt_id: str, prompt_config: PromptConfigData, state: State
    ) -> dict:
        """Run a System One entry and store its answers under the result variable.

        Every failure is raised as DecisionTableError with our own
        wording, so provider and validation text never reaches the session messages.
        """
        config = prompt_config.system_one_config
        if config is None:
            raise DecisionTableError(f"System One entry '{prompt_id}' has no config.")

        try:
            questions = SYSTEM_ONE_QUESTIONS_ADAPTER.validate_python(prompt_config.questions)
        except ValidationError:
            raise DecisionTableError(
                f"System One entry '{prompt_id}' has no valid questions."
            ) from None

        resolved = self._resolve_input_map(prompt_config.input_map, state)
        state_sent = json.loads(json.dumps(resolved, default=str))
        if all(value is None for value in state_sent.values()):
            raise DecisionTableError(f"System One entry '{prompt_id}' has no input values.")

        try:
            result, usage = await evaluate(config, state_sent, questions)
        except SystemOneError as error:
            logger.opt(exception=error).error(
                "System One call failed for prompt '{}' in node '{}'", prompt_id, self.node_name
            )
            raise DecisionTableError(
                f"System One call failed for prompt '{prompt_id}': {error}"
            ) from error

        stored = result.model_dump(mode="json")
        result_var = self._store_prompt_result(prompt_config, stored, state)

        return {
            "prompt_text": json.dumps(state_sent, indent=2),
            "raw_response": json.dumps(stored),
            "parsed_result": stored,
            "result_variable": result_var,
            "usage": usage.model_dump(),
            "provider": result.provider,
            "model_version": result.model_version,
        }

    async def _execute_prompt(self, prompt_id: str, state: State) -> dict:
        """Execute an LLM prompt referenced by ID. Stores result in variables.
        Returns dict with prompt_text, raw_response, parsed_result, result_variable, usage."""
        prompt_config: PromptConfigData | None = self.node_data.prompts.get(prompt_id)
        if prompt_config is None:
            logger.warning(f"Prompt ID '{prompt_id}' not found in prompt library, skipping.")
            return {}

        if prompt_config.kind == SYSTEM_ONE_PROMPT_KIND:
            return await self._execute_system_one_prompt(prompt_id, prompt_config, state)

        llm_data = prompt_config.llm_data
        if llm_data is None:
            logger.warning(
                "Prompt '{}' has no LLM configuration (llm_id={})", prompt_id, prompt_config.llm_id
            )
            raise DecisionTableError(
                f'Prompt "{prompt_id}" has no LLM. '
                "Choose one for it, or set a default LLM for the node."
            )

        # Render prompt with current variables
        # Plain data: the prompt is the flow author's text and must not reach live DotDict objects.
        variables_dict = state["variables"].deep_dump()
        rendered_prompt = self._render_prompt(prompt_config.prompt_text, variables_dict)

        logger.debug(
            "Executing prompt '{}', result_variable='{}'",
            prompt_id,
            prompt_config.result_variable,
        )

        try:
            result, usage = await run_json_llm(
                prompt=rendered_prompt,
                llm=llm_data,
                output_schema=prompt_config.output_schema,
            )
        except Exception as error:
            raise prompt_llm_error(prompt_id, llm_data, error) from error

        # Capture raw response text before JSON parsing
        raw_response = str(result) if not isinstance(result, str) else result

        logger.debug(
            "Prompt '{}' completed. Tokens: {}, Result type: {}",
            prompt_id,
            usage.total_tokens,
            type(result).__name__,
        )

        result_var = self._store_prompt_result(prompt_config, result, state)

        return {
            "prompt_text": rendered_prompt,
            "raw_response": raw_response,
            "parsed_result": result,
            "result_variable": result_var,
            "usage": usage.model_dump(),
        }

    def _indent_code(self, code: str) -> str:
        """Indent code block by 4 spaces for wrapping inside a function."""
        lines = code.split("\n")
        return "\n".join("    " + line for line in lines)

    def _log_unexpected_error(self, error: Exception, where: str) -> tuple[str, str]:
        """Log an error the node doesn't expect, and return the message citing the log line.

        The exception text can quote variables, code or provider details, so it stays in
        the log.

        Returns:
            The message to show, and its reference.
        """
        reference = log_with_reference(
            "Classification decision table '{}' failed with an unexpected error in {}: {}: {}",
            self.node_name,
            where,
            type(error).__name__,
            error,
            exception=error,
        )
        public_message = build_public_error_message(
            PublicErrorMessage.NODE_EXECUTION_FAILED, reference
        )
        return public_message, reference

    async def _show_error_and_route(
        self,
        state: State,
        writer: StreamWriter,
        error: Exception,
        public_message: str,
        reference: str | None,
    ) -> None:
        """Show the error, then set the error route, or fail the session if there is none.

        Raises:
            NodeExecutionError: The node has no error route; the session fails repeating
                `public_message`.
        """
        msg = self.custom_session_message_writer.add_error_message(
            session_id=self.session_id,
            node_name=self.node_name,
            writer=writer,
            execution_order=self.execution_order(state),
            node_type=self.TYPE,
            public_details=public_message,
        )
        await self._publish_message(msg)
        if self.node_data.next_error_node is None:
            raise NodeExecutionError(public_message, reference=reference) from error
        state["system_variables"]["nodes"][self.node_name]["result_node"] = (
            self.node_data.next_error_node
        )

    def execution_order(self, state: State):
        return state["system_variables"]["nodes"][self.node_name]["execution_order"]

    def build(self) -> CompiledStateGraph:
        """Build the classification decision table subgraph."""

        enter_node = self.node_data.node_name
        evaluate_node = self.node_data.node_name + "_evaluate"

        # Sort condition groups by order, excluding disabled (dock_visible=False) groups
        enabled_groups = [g for g in self.node_data.condition_groups if g.dock_visible]
        skipped = [g.group_name for g in self.node_data.condition_groups if not g.dock_visible]
        if skipped:
            logger.debug(
                "Skipping disabled condition groups in '{}': {}",
                self.node_data.node_name,
                skipped,
            )
        sorted_groups = sorted(
            enabled_groups,
            key=lambda g: g.order,
        )
        condition_expressions = [self._build_condition_expression(g) for g in sorted_groups]

        async def enter_node_function(state: State, writer: StreamWriter):
            logger.debug("Entering classification decision table: {}", self.node_name)

            update_variables = {
                "result_node": None,
                "default_node": self.node_data.default_next_node,
            }
            if state["system_variables"].get("nodes") is None:
                state["system_variables"]["nodes"] = {}

            order = state["system_variables"].get("execution_order", 0)
            state["system_variables"]["execution_order"] = order + 1

            if state["system_variables"]["nodes"].get(self.node_name) is None:
                state["system_variables"]["nodes"][self.node_name] = update_variables
            else:
                state["system_variables"]["nodes"][self.node_name].update(update_variables)
            state["system_variables"]["nodes"][self.node_name]["execution_order"] = order

            input_vars = state["variables"].model_dump()
            msg = self.custom_session_message_writer.add_start_message(
                session_id=self.session_id,
                node_name=self.node_name,
                writer=writer,
                input_=input_vars,
                execution_order=self.execution_order(state),
                node_type=self.TYPE,
            )
            await self._publish_message(msg)

            # Execute pre-computation. On an error route, the evaluate node finishes the
            # node without evaluating, since result_node is set.
            try:
                await self._execute_pre_computation(state)
            except StopSession:
                raise
            except (DecisionTableError, InvalidStatePathError) as error:
                logger.warning("Pre-computation error in '{}': {}", self.node_name, error)
                await self._show_error_and_route(state, writer, error, str(error), error.reference)
            except Exception as error:
                public_message, reference = self._log_unexpected_error(
                    error, PRE_COMPUTATION_SUBJECT
                )
                await self._show_error_and_route(state, writer, error, public_message, reference)

            return state

        async def route_to_error_node(
            state: State,
            writer: StreamWriter,
            error: Exception,
            public_message: str,
            reference: str | None,
        ):
            """Show the error and route to the error node, then finish.

            The finish closes the CDT message group in the UI, as on the
            pre-computation error path. The caller has already logged the raw
            error itself; `public_message` is the only text that reaches the
            client.

            Raises:
                NodeExecutionError: The node has no error route.
            """
            await self._show_error_and_route(state, writer, error, public_message, reference)
            decision_vars = state["system_variables"]["nodes"][self.node_name]
            msg = self.custom_session_message_writer.add_finish_message(
                session_id=self.session_id,
                node_name=self.node_name,
                writer=writer,
                output=decision_vars["result_node"],
                execution_order=self.execution_order(state),
                state=state,
                node_type=self.TYPE,
            )
            await self._publish_message(msg)
            return state

        async def evaluate_node_function(state: State, writer: StreamWriter):
            """Evaluate all condition groups top-to-bottom with continue/stop logic."""
            logger.debug("Evaluating classification decision table: {}", self.node_name)

            decision_vars = state["system_variables"]["nodes"][self.node_name]

            # If result already set (e.g., pre-computation error), skip
            if decision_vars["result_node"] is not None:
                msg = self.custom_session_message_writer.add_finish_message(
                    session_id=self.session_id,
                    node_name=self.node_name,
                    writer=writer,
                    output=decision_vars["result_node"],
                    execution_order=self.execution_order(state),
                    state=state,
                    node_type=self.TYPE,
                )
                await self._publish_message(msg)
                return state

            matched_next_node = None
            matched_condition_name = None

            group_index = 0
            while group_index < len(sorted_groups):
                group = sorted_groups[group_index]
                # Step 1: Evaluate the run of expression rows from here up to the
                # next match in one sandbox call. A row without an expression
                # matches without one.
                batch_expressions = list(
                    itertools.takewhile(bool, condition_expressions[group_index:])
                )
                # A failure of the batch run itself belongs to no single row.
                batch_subject = condition_subject(group.group_name)
                if len(batch_expressions) > 1:
                    last_group = sorted_groups[group_index + len(batch_expressions) - 1]
                    batch_subject = conditions_subject(group.group_name, last_group.group_name)
                failure_subject = batch_subject
                try:
                    if batch_expressions:
                        results, condition_failure = await self._evaluate_until_match(
                            batch_expressions, state, batch_subject
                        )
                    else:
                        results, condition_failure = [True], None
                    failure_subject = None

                    for expression_result in results:
                        group = sorted_groups[group_index]
                        msg = self.custom_session_message_writer.add_condition_group_message(
                            session_id=self.session_id,
                            node_name=self.node_name,
                            group_name=group.group_name,
                            result=expression_result,
                            writer=writer,
                            execution_order=self.execution_order(state),
                            expression=group.expression,
                        )
                        await self._publish_message(msg)
                        group_index += 1

                    if condition_failure is not None:
                        group = sorted_groups[group_index]
                        raise condition_error(group.group_name, condition_failure)

                    if not results[-1]:
                        continue

                    logger.debug("Condition '{}' matched.", group.group_name)
                    matched_condition_name = group.group_name

                    # Step 2: Execute prompt (if prompt_id is set)
                    if group.prompt_id:
                        prompt_result = await self._execute_prompt(group.prompt_id, state)
                        if prompt_result:
                            msg = self.custom_session_message_writer.add_classification_prompt_message(
                                session_id=self.session_id,
                                node_name=self.node_name,
                                writer=writer,
                                execution_order=self.execution_order(state),
                                prompt_id=group.prompt_id,
                                prompt_text=prompt_result.get("prompt_text", ""),
                                raw_response=prompt_result.get("raw_response", ""),
                                parsed_result=prompt_result.get("parsed_result"),
                                result_variable=prompt_result.get("result_variable", ""),
                                usage=prompt_result.get("usage", {}),
                                provider=prompt_result.get("provider"),
                                model_version=prompt_result.get("model_version"),
                            )
                            await self._publish_message(msg)

                    # Step 3: Execute manipulation (field_manipulations + main manipulation)
                    manipulation_sources = self._manipulation_sources(group)
                    if manipulation_sources:
                        vars_before = state["variables"].model_dump()
                        await self._execute_manipulation(
                            group.group_name, manipulation_sources, state
                        )
                        vars_after = state["variables"].model_dump()
                        changed = {k: v for k, v in vars_after.items() if vars_before.get(k) != v}
                        msg = self.custom_session_message_writer.add_condition_group_manipulation_message(
                            session_id=self.session_id,
                            node_name=self.node_name,
                            group_name=group.group_name,
                            state=state,
                            writer=writer,
                            execution_order=self.execution_order(state),
                            changed_variables=changed,
                        )
                        await self._publish_message(msg)

                    # Step 4: An explicit route is terminal — take it and stop, ignoring continue.
                    if group.next_node:
                        matched_next_node = group.next_node
                        break

                    # Step 5: No route on this row — honor continue flag (fall through if set).
                    if not group.continue_flag:
                        break

                except StopSession:
                    raise
                except DecisionTableError as error:
                    logger.warning(
                        "Classification decision table '{}' failed: {}", self.node_name, error
                    )
                    return await route_to_error_node(
                        state, writer, error, str(error), error.reference
                    )
                except Exception as error:
                    public_message, reference = self._log_unexpected_error(
                        error, failure_subject or condition_subject(group.group_name)
                    )
                    return await route_to_error_node(
                        state, writer, error, public_message, reference
                    )

            decision_vars["result_node"] = (
                matched_next_node or self.node_data.default_next_node or END
            )

            # Execute post-computation (sandboxed via RunPythonCodeService)
            try:
                await self._execute_post_computation(state)
            except StopSession:
                raise
            except (DecisionTableError, InvalidStatePathError) as error:
                logger.warning("Post-computation error in '{}': {}", self.node_name, error)
                return await route_to_error_node(state, writer, error, str(error), error.reference)
            except Exception as error:
                public_message, reference = self._log_unexpected_error(
                    error, POST_COMPUTATION_SUBJECT
                )
                return await route_to_error_node(state, writer, error, public_message, reference)

            logger.debug(
                "Classification table '{}' result: result_node={}",
                self.node_name,
                decision_vars["result_node"],
            )

            msg = self.custom_session_message_writer.add_finish_message(
                session_id=self.session_id,
                node_name=self.node_name,
                writer=writer,
                output=decision_vars["result_node"],
                execution_order=self.execution_order(state),
                state=state,
                node_type=self.TYPE,
                matched_condition=matched_condition_name,
            )
            await self._publish_message(msg)

            return state

        # Build the subgraph: enter → evaluate → END
        self._graph_builder.add_node(enter_node, enter_node_function)
        self._graph_builder.add_node(evaluate_node, evaluate_node_function)
        self._graph_builder.add_edge(START, enter_node)
        self._graph_builder.add_edge(enter_node, evaluate_node)
        self._graph_builder.add_edge(evaluate_node, END)

        return self._graph_builder.compile()
