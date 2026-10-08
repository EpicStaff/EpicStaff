import itertools
import json
import re
from typing import Any

import litellm
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamWriter
from loguru import logger
from src.crew.models.graph_models import (
    GraphMessage,
)
from src.crew.models.state import State
from src.crew.services.graph.custom_message_writer import CustomSessionMessageWriter
from src.crew.services.graph.events import StopEvent
from src.crew.services.graph.session_audit_provider import emit_session_audit_event
from src.crew.services.run_python_code_service import RunPythonCodeService
from src.shared.models import LLMData, PythonCodeData, TokenUsage
from src.shared.models.graph_nodes import (
    ClassificationConditionGroupData,
    ClassificationDecisionTableNodeData,
    PromptConfigData,
)

# litellm reports json_schema support for these providers, but their APIs reject it
# ("This response_format type is unavailable now") and only accept json_object.
JSON_OBJECT_ONLY_PROVIDERS = {"deepseek"}

# Provider rows whose name is not a litellm provider, mapped to the litellm provider their
# stored model names are prefixed with (e.g. "google_ai" rows hold "gemini/gemini-flash-latest").
PROVIDER_ALIASES = {
    "google_ai": "gemini",
    "novita_ai": "novita",
    "aws_sagemaker": "sagemaker",
    "featherless-ai": "featherless_ai",
}

# Expressions arrive as data and are compiled one at a time, so a syntax error in a
# row after the match never surfaces. Each row gets a fresh variable namespace;
# builtins, sys.modules and imported modules are shared by all rows of a batch.
# Lookup order matches the old per-row code, where the expression sat inside main():
# `variables`, then the identifier-named variables, then the sandbox module globals
# (json, os, sys, DotDict, get_secret, ...).
_EVALUATE_UNTIL_MATCH_CODE = """
import traceback
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
            assert isinstance(result, bool), "Expression must return a boolean value"
        # BaseException so that exit() in an expression is reported against its row.
        except BaseException as error:
            message = "".join(traceback.format_exception_only(type(error), error)).strip()
            return {"results": results, "error": message}
        results.append(result)
        if result:
            break
    return {"results": results, "error": None}
"""


def extract_first_json_object(text: str) -> Any:
    """Extract the first JSON object from a text string."""
    cleaned = text.replace("```", "")
    cleaned = re.sub(r"\bjson\b", "", cleaned, flags=re.IGNORECASE)

    start = cleaned.find("{")
    if start == -1:
        return text

    depth = 0
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start : i + 1]
                try:
                    return json.loads(candidate)
                except Exception:
                    return text
    return text


class ClassificationDecisionTableNodeError(Exception):
    """Custom exception for errors related to ClassificationDecisionTableNode."""


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

    def _publish_message(self, graph_message: GraphMessage):
        """Add a GraphMessage directly to the graph message stream.
        Subgraph StreamWriter messages don't propagate to the parent graph's
        astream, so we write to Redis directly instead - and, since that
        also means _emit_session_audit_event's own interception point (the
        parent's astream loop) never sees these chunks either, dispatch to
        the audit pipeline explicitly here too, right alongside the primary
        write (same data dict, same uuid, so both pipelines agree on the
        event's identity)."""
        if self.redis_service is None:
            return
        data = graph_message.to_payload()
        encoded_data = GraphMessage.encode_payload(data)
        self.redis_service.add_graph_message(data["uuid"], encoded_data)
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
        import re

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
        label: str,
    ) -> None:
        """Execute computation via sandboxed RunPythonCodeService."""
        if python_code is None or not python_code.code.strip():
            return

        inputs = self._resolve_input_map(input_map, state)

        result = await RunPythonCodeService(redis_service=self.redis_service).run_code(
            python_code_data=python_code,
            inputs=inputs,
            stop_event=self.stop_event,
        )

        if result["returncode"] != 0:
            raise ClassificationDecisionTableNodeError(
                f"{label} execution failed: {result['stderr']}"
            )

        if output_variable_path:
            from utils.set_output_variables import set_output_variables

            output = json.loads(result["result_data"])
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
            label="Pre-computation",
        )

    async def _execute_post_computation(self, state: State) -> None:
        """Execute post-computation via sandbox."""
        await self._execute_computation(
            python_code=self.node_data.post_python_code,
            input_map=self.node_data.post_input_map,
            output_variable_path=self.node_data.post_output_variable_path,
            state=state,
            label="Post-computation",
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
        self, expressions: list[str], state: State
    ) -> tuple[list[bool], str | None]:
        """Evaluate row expressions in order, in one sandbox run, up to the first match.

        Only a matched row changes state, so every row up to the next match sees the
        same variables and can share one run. Evaluation stops at the first True or the
        first failing expression; later expressions are never compiled or run. The
        whole batch shares one SANDBOX_EXECUTION_TIMEOUT.

        Returns:
            The result of each evaluated row, and the error message of the row right
            after them (index `len(results)`) if that row failed, else None.

        Raises:
            ClassificationDecisionTableNodeError: The sandbox run itself failed or
                returned an unreadable result.
        """
        result = await RunPythonCodeService(redis_service=self.redis_service).run_code(
            python_code_data=PythonCodeData(
                venv_name="default",
                code=_EVALUATE_UNTIL_MATCH_CODE,
                entrypoint="main",
                libraries=[],
            ),
            inputs={
                "expressions": expressions,
                "variables": state["variables"].model_dump(),
            },
            stop_event=self.stop_event,
        )

        if result["returncode"] != 0:
            raise ClassificationDecisionTableNodeError(
                f"Expression execution failed: {result['stderr']}"
            )
        try:
            evaluation = json.loads(result["result_data"])
            return evaluation["results"], evaluation["error"]
        except (TypeError, ValueError, KeyError) as error:
            raise ClassificationDecisionTableNodeError(
                f"Expression execution returned an unreadable result: {result['result_data']!r}"
            ) from error

    async def _execute_manipulation(self, manipulation: str, state: State) -> None:
        """Execute manipulation code in sandbox. Updates state variables."""
        variables_dict = state["variables"].model_dump()

        var_assignments = self._build_var_assignments(list(variables_dict.keys()))

        code = f"""
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

{self._indent_code(manipulation)}

    # Write back from namespace to dict
    return _from_ns(variables)
"""
        python_code_data = PythonCodeData(
            venv_name="default",
            code=code,
            entrypoint="main",
            libraries=[],
        )

        variables_dict = state["variables"].model_dump()

        result = await RunPythonCodeService(redis_service=self.redis_service).run_code(
            python_code_data=python_code_data,
            inputs={"variables": variables_dict},
            stop_event=self.stop_event,
        )

        if result["returncode"] != 0:
            raise ClassificationDecisionTableNodeError(
                f"Manipulation execution failed: {result['stderr']}"
            )

        variables = json.loads(result["result_data"])
        state["variables"].update(variables)

    async def _run_json_llm(
        self, prompt: str, llm: LLMData, output_schema: dict | str | None = None
    ) -> tuple[Any, TokenUsage]:
        """Call LLM via litellm and parse JSON response."""
        llm_config = llm.config
        litellm.drop_params = True

        response_format = None
        schema = output_schema
        if isinstance(schema, str) and schema.strip():
            try:
                schema = json.loads(schema)
            except (ValueError, TypeError):
                logger.warning(
                    "Prompt output_schema is not valid JSON; sending request without a response_format."
                )
                schema = None
        messages = [{"role": "user", "content": prompt}]
        if isinstance(schema, dict) and schema:
            if llm.provider.lower().strip() in JSON_OBJECT_ONLY_PROVIDERS:
                response_format = {"type": "json_object"}
                # json_object mode carries no schema and requires the word "json" in the
                # prompt; the user-written prompt guarantees neither, so state both here.
                messages.insert(
                    0,
                    {
                        "role": "system",
                        "content": (
                            "Respond with a JSON object that matches this JSON schema: "
                            f"{json.dumps(schema)}"
                        ),
                    },
                )
            else:
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "cdt_prompt_output",
                        "schema": schema,
                        "strict": True,
                    },
                }

        # Many stored model names already carry their provider prefix (e.g. "ollama/mistral").
        # Only the row's own provider counts: "openai/gpt-oss-120b" on a Groq row is a Groq
        # model id and must become "groq/openai/gpt-oss-120b".
        litellm_provider = PROVIDER_ALIASES.get(llm.provider.lower().strip(), llm.provider)
        model = (
            llm_config.model
            if llm_config.model.startswith(f"{litellm_provider}/")
            else f"{litellm_provider}/{llm_config.model}"
        )
        params = {
            "model": model,
            "timeout": llm_config.timeout,
            "temperature": llm_config.temperature,
            "top_p": llm_config.top_p,
            "stop": llm_config.stop,
            "max_tokens": llm_config.max_tokens,
            "presence_penalty": llm_config.presence_penalty,
            "frequency_penalty": llm_config.frequency_penalty,
            "logit_bias": llm_config.logit_bias,
            "response_format": response_format,
            "seed": llm_config.seed,
            "base_url": llm_config.base_url,
            "api_version": llm_config.api_version,
            "api_key": llm_config.api_key,
            "stream": False,
        }
        resp = await litellm.acompletion(**{**params, "messages": messages})

        try:
            cost = litellm.completion_cost(completion_response=resp)
        except Exception:
            cost = 0.0  # litellm raises for models without a pricing entry — don't crash CDT

        cached_tokens = 0
        details = (
            getattr(resp.usage, "prompt_tokens_details", None) if hasattr(resp, "usage") else None
        )
        if details is not None:
            cached_tokens = getattr(details, "cached_tokens", 0) or 0

        usage = TokenUsage(
            total_tokens=getattr(resp.usage, "total_tokens", 0) if hasattr(resp, "usage") else 0,
            prompt_tokens=getattr(resp.usage, "prompt_tokens", 0) if hasattr(resp, "usage") else 0,
            completion_tokens=getattr(resp.usage, "completion_tokens", 0)
            if hasattr(resp, "usage")
            else 0,
            successful_requests=1,
            cached_prompt_tokens=cached_tokens,
            total_cost_usd=cost,
        )

        content = resp.choices[0].message.content
        if not isinstance(content, str):
            return content, usage
        return extract_first_json_object(content), usage

    def _render_prompt(self, prompt_text: str, variables: dict) -> str:
        """Render prompt template with variable interpolation using {var_name} syntax."""
        try:
            return prompt_text.format(**variables)
        except (KeyError, IndexError):
            # If template vars don't match, return as-is
            return prompt_text

    async def _execute_prompt(self, prompt_id: str, state: State) -> dict:
        """Execute an LLM prompt referenced by ID. Stores result in variables.
        Returns dict with prompt_text, raw_response, parsed_result, result_variable, usage."""
        prompt_config: PromptConfigData | None = self.node_data.prompts.get(prompt_id)
        if prompt_config is None:
            logger.warning(f"Prompt ID '{prompt_id}' not found in prompt library, skipping.")
            return {}

        llm_data = prompt_config.llm_data
        if llm_data is None:
            raise ClassificationDecisionTableNodeError(
                f"No LLM configuration resolved for prompt '{prompt_id}' (llm_id={prompt_config.llm_id})"
            )

        # Render prompt with current variables
        variables_dict = state["variables"].model_dump()
        rendered_prompt = self._render_prompt(prompt_config.prompt_text, variables_dict)

        logger.info(
            f"Executing prompt '{prompt_id}' with LLM {llm_data.provider}/{llm_data.config.model}, "
            f"result_variable='{prompt_config.result_variable}'"
        )

        try:
            result, usage = await self._run_json_llm(
                prompt=rendered_prompt,
                llm=llm_data,
                output_schema=prompt_config.output_schema,
            )
        except Exception as e:
            error_msg = f"ERROR Prompt '{prompt_id}' LLM call failed: {type(e).__name__}: {e}"
            logger.info(error_msg)
            raise ClassificationDecisionTableNodeError(
                f"LLM call failed for prompt '{prompt_id}': {type(e).__name__}: {e}"
            ) from e

        # Capture raw response text before JSON parsing
        raw_response = str(result) if not isinstance(result, str) else result

        logger.info(
            f"Prompt '{prompt_id}' completed. "
            f"Tokens: {usage.total_tokens}, "
            f"Result type: {type(result).__name__}"
        )

        # Store result in state variables under result_variable
        result_var = prompt_config.result_variable or "prompt_result"
        state["variables"].update({result_var: result})

        # Apply variable_mappings: extract specific fields from result into state variables
        if prompt_config.variable_mappings and isinstance(result, dict):
            for state_var, result_field in prompt_config.variable_mappings.items():
                if result_field in result:
                    state["variables"].update({state_var: result[result_field]})
                    logger.info(f"Mapped result.{result_field} -> variables.{state_var}")

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
            logger.info(
                f"Skipping disabled condition groups in '{self.node_data.node_name}': {skipped}"
            )
        sorted_groups = sorted(
            enabled_groups,
            key=lambda g: g.order,
        )
        condition_expressions = [self._build_condition_expression(g) for g in sorted_groups]

        async def enter_node_function(state: State, writer: StreamWriter):
            logger.info(f"Entering classification decision table: {self.node_name}")

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
            self._publish_message(msg)

            # Execute pre-computation
            try:
                await self._execute_pre_computation(state)
            except ClassificationDecisionTableNodeError as e:
                logger.error(f"Pre-computation error: {e}")
                state["system_variables"]["nodes"][self.node_name]["result_node"] = (
                    self.node_data.next_error_node or END
                )
                msg = self.custom_session_message_writer.add_error_message(
                    session_id=self.session_id,
                    node_name=self.node_name,
                    error=str(e),
                    writer=writer,
                    execution_order=self.execution_order(state),
                    node_type=self.TYPE,
                )
                self._publish_message(msg)
                return state

            return state

        def route_to_error_node(state: State, writer: StreamWriter, error: str):
            """Route to the error node and publish error, then finish.

            The finish closes the CDT message group in the UI, as on the
            pre-computation error path."""
            decision_vars = state["system_variables"]["nodes"][self.node_name]
            decision_vars["result_node"] = self.node_data.next_error_node or END
            msg = self.custom_session_message_writer.add_error_message(
                session_id=self.session_id,
                node_name=self.node_name,
                error=error,
                writer=writer,
                execution_order=self.execution_order(state),
                node_type=self.TYPE,
            )
            self._publish_message(msg)
            msg = self.custom_session_message_writer.add_finish_message(
                session_id=self.session_id,
                node_name=self.node_name,
                writer=writer,
                output=decision_vars["result_node"],
                execution_order=self.execution_order(state),
                state=state,
                node_type=self.TYPE,
            )
            self._publish_message(msg)
            return state

        async def evaluate_node_function(state: State, writer: StreamWriter):
            """Evaluate all condition groups top-to-bottom with continue/stop logic."""
            logger.info(f"Evaluating classification decision table: {self.node_name}")

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
                self._publish_message(msg)
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
                batch_failure_scope = None
                if len(batch_expressions) > 1:
                    last_group = sorted_groups[group_index + len(batch_expressions) - 1]
                    batch_failure_scope = (
                        f"evaluating conditions from '{group.group_name}' "
                        f"to '{last_group.group_name}'"
                    )
                try:
                    if batch_expressions:
                        results, expression_error = await self._evaluate_until_match(
                            batch_expressions, state
                        )
                    else:
                        results, expression_error = [True], None
                    batch_failure_scope = None

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
                        self._publish_message(msg)
                        group_index += 1

                    if expression_error is not None:
                        group = sorted_groups[group_index]
                        raise ClassificationDecisionTableNodeError(
                            f"Expression execution failed: {expression_error}"
                        )

                    if not results[-1]:
                        continue

                    logger.info(f"Condition '{group.group_name}' matched.")
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
                            )
                            self._publish_message(msg)

                    # Step 3: Execute manipulation (field_manipulations + main manipulation)
                    manip_parts = []
                    if group.field_manipulations:
                        for var_name, var_expr in group.field_manipulations.items():
                            if var_expr and var_expr.strip():
                                target = var_name.strip()
                                if not target.startswith("variables."):
                                    target = f"variables.{target}"
                                manip_parts.append(f"{target} = {var_expr.strip()}")
                    if group.manipulation:
                        manip_parts.append(group.manipulation)
                    combined_manipulation = "\n".join(manip_parts) if manip_parts else None

                    if combined_manipulation:
                        vars_before = state["variables"].model_dump()
                        await self._execute_manipulation(combined_manipulation, state)
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
                        self._publish_message(msg)

                    # Step 4: An explicit route is terminal — take it and stop, ignoring continue.
                    if group.next_node:
                        matched_next_node = group.next_node
                        break

                    # Step 5: No route on this row — honor continue flag (fall through if set).
                    if not group.continue_flag:
                        break

                except ClassificationDecisionTableNodeError as e:
                    scope = batch_failure_scope or f"in condition '{group.group_name}'"
                    error = f"Error {scope}: {e}"
                    logger.info(f"ERROR {error}")
                    return route_to_error_node(state, writer, error)
                except Exception as e:
                    scope = batch_failure_scope or f"in condition '{group.group_name}'"
                    error = f"Unexpected error {scope}: {type(e).__name__}: {e}"
                    logger.info(f"ERROR {error}")
                    return route_to_error_node(state, writer, error)

            decision_vars["result_node"] = (
                matched_next_node or self.node_data.default_next_node or END
            )

            # Execute post-computation (sandboxed via RunPythonCodeService)
            try:
                await self._execute_post_computation(state)
            except ClassificationDecisionTableNodeError as e:
                logger.error(f"Post-computation error: {e}")
                return route_to_error_node(state, writer, str(e))

            logger.info(
                f"Classification table '{self.node_name}' result: "
                f"result_node={decision_vars['result_node']}"
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
            self._publish_message(msg)

            return state

        # Build the subgraph: enter → evaluate → END
        self._graph_builder.add_node(enter_node, enter_node_function)
        self._graph_builder.add_node(evaluate_node, evaluate_node_function)
        self._graph_builder.add_edge(START, enter_node)
        self._graph_builder.add_edge(enter_node, evaluate_node)
        self._graph_builder.add_edge(evaluate_node, END)

        return self._graph_builder.compile()
