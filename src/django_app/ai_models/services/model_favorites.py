"""A person's favorite LLM models, named as the model catalog lists them."""

from django.db.models import Q, QuerySet
from tables.models.user import User

from ai_models.domain.specs import ModelKind
from ai_models.models import LLMModel, LLMModelFavorite
from ai_models.repository import CatalogRepository
from ai_models.services.catalog_model_resolver import (
    CatalogModelResolver,
    UnknownCatalogModelError,
)


class UnknownFavoriteModelError(Exception):
    """No stored model row the active organization sees matches the names given."""


class ModelFavoritesService:
    """Star, unstar and list a person's favorite LLM models by provider and model name.

    The config form names a model the way the catalog does, so this does too. A star
    points at the model row a config of that name would use (`CatalogModelResolver`),
    which keeps its id when the catalog is seeded again. A starred row is listed under
    its catalog name, so a built-in row stored under another name of a catalog model
    (provider-prefixed, an alias's) is that catalog model. Only rows the active
    organization sees count: built-in rows and its own custom rows, never another
    organization's, even when the person belongs to both.
    """

    def __init__(self, repository: CatalogRepository | None = None) -> None:
        self._repository = repository or CatalogRepository.default()

    def favorite_names(self, provider: str, *, org_id: int, user: User | None) -> set[str]:
        """Return the names of `user`'s favorite models of `provider`, as the catalog lists them.

        One query, however many favorites there are. None (a caller that is not a
        person) has none.
        """
        if user is None:
            return set()
        rows = self._favorite_rows(provider, org_id=org_id, user=user)
        return {self._listed_name(row.llm_provider.name, row.name) for row in rows}

    def add(self, provider: str, model_name: str, *, org_id: int, user: User) -> None:
        """Star the model; starring a favorite again changes nothing.

        Raises:
            UnknownFavoriteModelError: The active organization has no stored row of
                the model, as for a custom name no config has saved yet.
        """
        try:
            row = CatalogModelResolver(self._repository).resolve(
                ModelKind.LLM, provider, model_name, org_id=org_id, author=user
            )
        except UnknownCatalogModelError as error:
            raise UnknownFavoriteModelError(str(error)) from error
        if row.pk is None:
            raise UnknownFavoriteModelError(
                f"Unknown model '{model_name.strip()}' for provider '{provider}'."
            )
        LLMModelFavorite.objects.get_or_create(user=user, llm_model=row)

    def remove(self, provider: str, model_name: str, *, org_id: int, user: User) -> None:
        """Unstar the model, whichever of its rows the star points at.

        Unstarring a model that is not a favorite, or that the catalog no longer
        lists, changes nothing.
        """
        name = self._listed_name(provider, model_name)
        row_ids = [
            row.pk
            for row in self._favorite_rows(provider, org_id=org_id, user=user)
            if self._listed_name(row.llm_provider.name, row.name) == name
        ]
        LLMModelFavorite.objects.filter(user=user, llm_model_id__in=row_ids).delete()

    def _favorite_rows(self, provider: str, *, org_id: int, user: User) -> QuerySet[LLMModel]:
        provider_spec = self._repository.provider(provider)
        provider_names = (
            (provider_spec.name, *provider_spec.aliases) if provider_spec else (provider,)
        )
        return LLMModel.objects.filter(
            Q(org__isnull=True) | Q(org_id=org_id),
            favorited_by__user=user,
            llm_provider__name__in=provider_names,
        ).select_related("llm_provider")

    def _listed_name(self, provider: str, model_name: str) -> str:
        """The name the catalog's model list gives the model: its catalog name, else its own."""
        model_name = model_name.strip()
        catalog_model = self._repository.model(ModelKind.LLM, provider, model_name)
        return catalog_model.name if catalog_model else model_name
