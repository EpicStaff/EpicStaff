import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from asgiref.sync import async_to_sync
from tables.constants.cdt_explanation_limits import (
    MAX_EXPLANATION_TEXT_LENGTH,
    MAX_GENERATED_BY_LENGTH,
)
from tables.exceptions import (
    CdtExplainLLMConfigInvalidError,
    CdtExplainLLMConfigMissingKeyError,
    CdtExplainLLMConfigNotFoundError,
    CdtExplainUpstreamError,
    ClassificationDecisionTableNodeNotFoundError,
)
from tables.models.graph_models import ClassificationDecisionTableNode
from tables.models.llm_models import LLMConfig
from tables.services.llm_clients import get_llm_client, resolve_llm_api_key
from tables.services.llm_clients.base import (
    DoneEvent,
    InvalidLLMConfigError,
    TokenEvent,
    UnsupportedLLMProviderError,
)

from .context import render_user_message
from .output_schema import CDT_EXPLAIN_OUTPUT_SCHEMA
from .system_prompt import build_system_prompt, section_key

logger = logging.getLogger(__name__)

BATCH_SIZE = 6
MAX_CONCURRENCY = 5


@dataclass
class ExplainResult:
    explanations: list[dict]
    failures: list[dict]
    generated_by: str


class CdtExplainService:
    """Generates plain-language explanations of CDT steps.

    Block content comes from the request body, not the database: the dialog opens
    over a panel that may hold unsaved edits, and the explanation has to describe
    what the user is looking at. The node id is used for org scoping only.
    """

    def explain(
        self, *, pk, org_id: int, llm_config_id: int, table: dict, blocks: list[dict]
    ) -> ExplainResult:
        self._assert_node_visible(pk, org_id)
        llm_config = self._get_llm_config_or_404(llm_config_id, org_id)

        api_key = resolve_llm_api_key(llm_config, context="CdtExplain.llm_config.api_key")
        try:
            client = get_llm_client(
                llm_config, output_schema=CDT_EXPLAIN_OUTPUT_SCHEMA, api_key=api_key
            )
        except UnsupportedLLMProviderError as exc:
            raise CdtExplainLLMConfigNotFoundError(llm_config_id) from exc
        except InvalidLLMConfigError as exc:
            raise CdtExplainLLMConfigInvalidError(str(exc)) from exc

        batches = list(self._batches(blocks))
        texts, failed_batches = async_to_sync(self._run_batches)(client, table, batches)

        if failed_batches == len(batches):
            if not api_key:
                raise CdtExplainLLMConfigMissingKeyError(llm_config_id)
            raise CdtExplainUpstreamError()

        generated_by = self._model_label(llm_config)
        explanations, failures = [], []
        for block in blocks:
            text = texts.get(block["id"])
            if isinstance(text, str) and text:
                # Clamped so a generated explanation always fits what a node can store.
                explanations.append(
                    {
                        "id": block["id"],
                        "text": text[:MAX_EXPLANATION_TEXT_LENGTH],
                        "generated_by": generated_by,
                    }
                )
            else:
                failures.append(
                    {"id": block["id"], "detail": "No explanation was generated for this step."}
                )
        return ExplainResult(explanations, failures, generated_by)

    @staticmethod
    def _assert_node_visible(pk, org_id: int) -> None:
        exists = ClassificationDecisionTableNode.objects.filter(
            pk=pk, graph__org_id=org_id
        ).exists()
        if not exists:
            raise ClassificationDecisionTableNodeNotFoundError(pk)

    @staticmethod
    def _get_llm_config_or_404(llm_config_id: int, org_id: int) -> LLMConfig:
        config = (
            LLMConfig.objects.select_related("model__llm_provider")
            .filter(pk=llm_config_id, org_id=org_id)
            .first()
        )
        if config is None:
            raise CdtExplainLLMConfigNotFoundError(llm_config_id)
        return config

    @staticmethod
    def _model_label(llm_config: LLMConfig) -> str:
        model = llm_config.model
        label = (model.name if model and model.name else llm_config.custom_name) or "Default LLM"
        # Both names are unbounded text, but the frontend stores this label as an
        # explanation's `generatedBy`, which is capped.
        return label[:MAX_GENERATED_BY_LENGTH]

    @staticmethod
    def _batches(blocks: list[dict]) -> Iterator[list[dict]]:
        groups: dict[str, list[dict]] = defaultdict(list)
        for block in blocks:
            groups[section_key(block["block"])].append(block)
        for key in sorted(groups):
            items = groups[key]
            for start in range(0, len(items), BATCH_SIZE):
                yield items[start : start + BATCH_SIZE]

    async def _run_batches(
        self, client, table: dict, batches: list[list[dict]]
    ) -> tuple[dict[str, str], int]:
        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

        async def guarded(batch):
            async with semaphore:
                return await self._explain_batch(client, table, batch)

        results = await asyncio.gather(
            *(guarded(batch) for batch in batches), return_exceptions=True
        )

        texts: dict[str, str] = {}
        failed = 0
        for batch, result in zip(batches, results, strict=False):
            if isinstance(result, BaseException):
                failed += 1
                logger.warning(
                    "CDT explain batch failed (%d step(s)): %s",
                    len(batch),
                    result,
                    exc_info=result,
                )
                continue
            texts.update(result)
        return texts, failed

    async def _explain_batch(self, client, table: dict, batch: list[dict]) -> dict[str, str]:
        messages = [
            {"role": "system", "content": build_system_prompt(b["block"] for b in batch)},
            {"role": "user", "content": render_user_message(table, batch)},
        ]

        chunks: list[str] = []
        async for event in client.stream_completion(messages, []):
            if isinstance(event, DoneEvent):
                break
            if isinstance(event, TokenEvent):
                chunks.append(event.content)

        wanted = {b["id"] for b in batch}
        return {
            item["id"]: item["text"]
            for item in self._parse("".join(chunks))
            if item.get("id") in wanted and item.get("text")
        }

    @staticmethod
    def _parse(raw: str) -> Iterable[dict]:
        text = raw.strip()
        if text.startswith("```"):
            fenced = text.split("```")
            text = fenced[1] if len(fenced) > 1 else text.strip("`")
            text = text.removeprefix("json").strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CdtExplainUpstreamError("The model did not return a usable response.") from exc
        items = payload.get("explanations") if isinstance(payload, dict) else None
        return items if isinstance(items, list) else []
