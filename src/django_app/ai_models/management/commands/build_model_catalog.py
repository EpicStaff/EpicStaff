from pathlib import Path
from typing import NoReturn

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import ai_models
from ai_models.domain.builder import CatalogBuilder
from ai_models.domain.catalog import Catalog
from ai_models.domain.checks import (
    CatalogChecker,
    CatalogUpToDateRule,
    ChoiceOptionsRequiredRule,
    ConnectionFieldsRequiredRule,
    NoDraftParametersRule,
    NumberRangeRequiredRule,
    UnclassifiedThinkingModelRule,
    UnusedRegistryEntryRule,
)
from ai_models.domain.discovery import (
    EmbeddingParameterDiscoveryStrategy,
    LLMParameterDiscoveryStrategy,
    TranscriptionParameterDiscoveryStrategy,
)
from ai_models.domain.registry import ParameterRegistry
from ai_models.domain.value_types import ValueTypeRegistry
from ai_models.litellm_adapter import CatalogSourceError, LiteLLMAdapter

DATA_DIRECTORY = Path(ai_models.__file__).parent / "data"
REGISTRY_PATH = DATA_DIRECTORY / "parameter_registry.yaml"
CATALOG_PATH = DATA_DIRECTORY / "catalog.json"

_CHECK_RULES = (
    NoDraftParametersRule(),
    NumberRangeRequiredRule(),
    ChoiceOptionsRequiredRule(),
    CatalogUpToDateRule(),
    ConnectionFieldsRequiredRule(),
    UnusedRegistryEntryRule(),
    UnclassifiedThinkingModelRule(LiteLLMAdapter()),
)


class Command(BaseCommand):
    help = (
        "Write ai_models/data/catalog.json from the installed LiteLLM and "
        "parameter_registry.yaml, and print what changed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help=(
                "Write nothing; print every problem keeping catalog.json from being complete "
                "and current, and exit 1 on any error."
            ),
        )

    def handle(self, *args, check: bool, **options):
        # The catalog must be reproducible from the pinned LiteLLM release, so its model
        # map must be the one bundled with it, never one fetched from upstream.
        adapter = LiteLLMAdapter()
        try:
            uses_bundled_model_map = adapter.uses_bundled_model_map()
        except CatalogSourceError as error:
            raise CommandError(str(error)) from error
        if not uses_bundled_model_map:
            raise CommandError(
                "Set LITELLM_LOCAL_MODEL_COST_MAP=True: without it LiteLLM fetches its "
                "model map from GitHub, and the catalog would not match the pinned release."
            )
        if settings.LITELLM_MODEL_COST_REFRESH_ENABLED:
            raise CommandError(
                "Turn LITELLM_MODEL_COST_REFRESH_ENABLED off: the daily refresh merges "
                "upstream model data into LiteLLM's bundled map."
            )

        registry = ParameterRegistry.load(REGISTRY_PATH)
        strategies = [
            LLMParameterDiscoveryStrategy(adapter, registry),
            EmbeddingParameterDiscoveryStrategy(adapter, registry),
            TranscriptionParameterDiscoveryStrategy(adapter, registry),
        ]
        try:
            catalog = CatalogBuilder(adapter, registry, strategies, ValueTypeRegistry()).build()
        except CatalogSourceError as error:
            raise CommandError(str(error)) from error

        if check:
            self._check(catalog, registry)

        previous = Catalog.from_json(CATALOG_PATH.read_text()) if CATALOG_PATH.exists() else None
        CATALOG_PATH.write_text(catalog.to_json() + "\n")
        for line in CatalogBuilder.changes(previous, catalog):
            self.stdout.write(line)

    def _check(self, fresh: Catalog, registry: ParameterRegistry) -> NoReturn:
        if not CATALOG_PATH.exists():
            raise CommandError(f"{CATALOG_PATH} is missing; run build_model_catalog.")
        committed = Catalog.from_json(CATALOG_PATH.read_text())
        findings = CatalogChecker(_CHECK_RULES).run(committed, fresh, registry)
        for finding in findings:
            if finding.is_error:
                self.stderr.write(f"error: {finding.rule}: {finding.message}")
            else:
                self.stdout.write(f"warning: {finding.rule}: {finding.message}")
        error_count = sum(finding.is_error for finding in findings)
        self.stdout.write(f"{error_count} error(s), {len(findings) - error_count} warning(s)")
        # Exits on success too, so callers and CI always get an explicit status.
        raise SystemExit(1 if error_count else 0)
