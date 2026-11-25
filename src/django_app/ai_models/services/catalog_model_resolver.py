"""Find the model row a config uses from a provider name and a model name."""

from django.db.models import Q
from src.shared.litellm_model_names import litellm_lookup_name
from src.shared.models import UserAction
from tables.models.user import User
from user_audit.recorder import record_user_action

from ai_models.domain.specs import ModelKind
from ai_models.models import EmbeddingModel, LLMModel, Provider
from ai_models.repository import CatalogRepository

_MODEL_CLASSES = {ModelKind.LLM: LLMModel, ModelKind.EMBEDDING: EmbeddingModel}
_PROVIDER_FIELDS = {LLMModel: "llm_provider", EmbeddingModel: "embedding_provider"}


class UnknownCatalogModelError(Exception):
    """No model row matches the names given, and none may be added for them.

    `field` is the input nothing matched, `provider` or `model_name`; the message says why.
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class CatalogModelResolver:
    """Resolve a provider and model name to the model row an organization's config uses.

    The API's config serializers and quickstart both name a model this way, so both
    pick the same row for the same names; the config form's model picker offers the
    organization's custom rows from here too.
    """

    def __init__(self, repository: CatalogRepository | None = None) -> None:
        self._repository = repository or CatalogRepository.default()

    def resolve(
        self,
        kind: ModelKind,
        provider: str,
        model_name: str,
        *,
        org_id: int,
        author: User | None,
    ) -> LLMModel | EmbeddingModel:
        """Return the row of `model_name`, or an unsaved custom row of the organization.

        `provider` may be any of the provider's catalog names, aliases included, and
        `model_name` its bare or provider-prefixed name. The visible built-in row of
        the catalog model wins over `org_id`'s own row of that model; other
        organizations' rows are never considered. Without either, a provider that
        takes custom models gets a new custom row of `org_id`, authored by `author`
        and not saved: pass it to `save_if_new` in the transaction that stores the config.

        Raises:
            UnknownCatalogModelError: Its `field` is `provider` when no provider row
                matches, `model_name` when nothing matches and the provider takes no
                custom models.
        """
        model_class = _MODEL_CLASSES[kind]
        provider_field = _PROVIDER_FIELDS[model_class]
        provider_spec = self._repository.provider(provider)
        provider_names = (
            (provider_spec.name, *provider_spec.aliases) if provider_spec else (provider,)
        )
        provider_rows = {row.name: row for row in Provider.objects.filter(name__in=provider_names)}
        if not provider_rows:
            raise UnknownCatalogModelError("provider", f"Unknown provider '{provider}'.")

        model_name = model_name.strip()
        catalog_model = self._repository.model(kind, provider, model_name)
        candidates = model_class.objects.filter(
            Q(org__isnull=True, is_custom=False, is_visible=True) | Q(org_id=org_id),
            **{
                f"{provider_field}__in": provider_rows.values(),
                "name__in": _stored_name_forms(model_name, catalog_model),
            },
        ).select_related(provider_field)
        matching = [
            row
            for row in candidates
            if self._is_same_model(kind, row, provider_field, model_name, catalog_model)
        ]
        if matching:
            return min(matching, key=lambda row: (row.org_id is not None, row.pk))

        if provider_spec is None or not provider_spec.custom_models:
            raise UnknownCatalogModelError(
                "model_name", f"Unknown model '{model_name}' for provider '{provider}'."
            )
        provider_row = next(provider_rows[name] for name in provider_names if name in provider_rows)
        return model_class(
            name=model_name,
            org_id=org_id,
            is_custom=True,
            predefined=False,
            created_by=author,
            **{provider_field: provider_row},
        )

    def custom_model_names(
        self, kind: ModelKind, provider: str, *, org_id: int, search: str = ""
    ) -> list[str]:
        """Return the names of `org_id`'s visible custom models of `provider`, sorted.

        `provider` may be any of the provider's catalog names, aliases included; a
        provider that takes no custom models has none. `search` matches part of the
        name, ignoring case. A name the catalog knows (as `resolve` matches it) is left
        out, so the picker lists that model once, as its catalog entry, or not at all
        once the catalog model is past its deprecation date.
        """
        provider_spec = self._repository.provider(provider)
        if provider_spec is None or not provider_spec.custom_models:
            return []
        model_class = _MODEL_CLASSES[kind]
        names = (
            model_class.objects.filter(
                org_id=org_id,
                is_custom=True,
                is_visible=True,
                name__icontains=search,
                **{
                    f"{_PROVIDER_FIELDS[model_class]}__name__in": (
                        provider_spec.name,
                        *provider_spec.aliases,
                    )
                },
            )
            .order_by("name")
            .values_list("name", flat=True)
            .distinct()
        )
        return [name for name in names if self._repository.model(kind, provider, name) is None]

    def save_if_new(self, model: LLMModel | EmbeddingModel) -> LLMModel | EmbeddingModel:
        """Return `model` once saved: an unsaved custom row from `resolve` is stored first.

        A concurrent request may have added a row of the same organization, name and
        provider since `resolve`; that row is returned instead, locked FOR NO KEY UPDATE
        until the caller's transaction ends, so the caller's config points at a row that
        still carries the name `resolve` was given. A rename of that row locks it too
        (`check_llm_model_write`), so it either waits and then counts the caller's
        config, or committed first: the row no longer matches, and the organization gets
        a new row of the name instead. A row this call creates is not visible to other
        transactions until the caller commits, so it needs no lock. Must run inside the
        transaction that stores the config.
        """
        if model.pk is not None:
            return model
        model_class = type(model)
        provider_field = _PROVIDER_FIELDS[model_class]
        identity = {
            "org_id": model.org_id,
            "name": model.name,
            provider_field: getattr(model, provider_field),
        }
        locking = model_class.objects.select_for_update(no_key=True, of=("self",))
        # Twice at most: the second try only runs when the matching row was renamed or
        # deleted between `get_or_create` and the lock.
        for _attempt in range(2):
            saved, created = model_class.objects.get_or_create(
                **identity,
                defaults={"is_custom": True, "predefined": False, "created_by": model.created_by},
            )
            if created:
                record_user_action(action=UserAction.CREATED, org_id=saved.org_id, target=saved)
                return saved
            locked = locking.filter(**identity).first()
            if locked is not None:
                return locked
        raise model_class.DoesNotExist(
            f"Model '{model.name}' changed twice while it was being saved; try again."
        )

    def _is_same_model(
        self, kind, row, provider_field: str, model_name: str, catalog_model
    ) -> bool:
        if catalog_model is None:
            return row.name == model_name
        provider_row = getattr(row, provider_field)
        return self._repository.model(kind, provider_row.name, row.name) == catalog_model


def _stored_name_forms(model_name: str, catalog_model) -> set[str]:
    """Return every name a row of this model may be stored under (bare or provider-prefixed)."""
    if catalog_model is None:
        return {model_name}
    lookup_name = litellm_lookup_name(catalog_model.provider, catalog_model.name)
    return {model_name, catalog_model.name, lookup_name, lookup_name.split("/", 1)[1]}
