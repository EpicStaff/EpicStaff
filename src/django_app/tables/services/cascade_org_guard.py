"""Keep a delete's cascade inside the organization of the row it started from.

The schema lets a row of one organization point at a row of another (a surface
owned by another organization's agent, a subflow node calling another
organization's flow). The API refuses such links, but the database doesn't, so
one written straight to the database would make a delete bin, null or remove
another organization's row. The guard resolves the organization of every row a
delete is about to change and refuses the whole delete on a mismatch: the
caller's transaction rolls back and nothing changes.

Rows without an organization are never a mismatch: a NULL `org` is a shared
built-in (a built-in tool) or a row from before org scoping, and a model with no
path to an organization (PythonCode, a User) isn't owned by one. A root without
an organization (a built-in tool the upload_tools command bins) turns the guard
off: it isn't one organization's delete.

A delete of many roots at once (the retention job's sweep of expired rows)
splits them by organization with `per_org`, so each row is held to its own.

A refusal is logged with the row it reaches and both organizations; the error
the caller gets names neither. A caller that tries many rows at once and then
retries them one by one to find the refused one turns the log off for the first
try (`log_refusal=False`), so each refused row is logged once.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from django.apps import apps
from django.db import models
from django.db.models import Q, QuerySet
from django.db.models.deletion import Collector
from tables.exceptions import CrossOrgCascadeError
from utils.logger import logger

# The longest chain of owner links a model's organization is looked up through
# (an inline surface's search config -> its knowledge link -> the inline
# surface -> the agent node -> the flow -> the org takes 5).
_MAX_OWNER_HOPS = 6


@cache
def org_paths(model: type[models.Model]) -> tuple[str, ...]:
    """Return the ORM lookups from a row of `model` to the id of the organization owning it.

    A model with a foreign key to Organization (its `org`) is owned through that
    column alone. Any other model is owned through its CASCADE foreign keys, minus
    the ones in `soft_delete_reference_fields` (those only point at a row), each
    owner resolved the same way. A link row can have more than one owner (a
    GraphRAG's document link belongs to the GraphRAG and to the document), so this
    returns every path. Empty when no path reaches an organization.
    """
    return _org_paths(model, frozenset({model}))


def _org_paths(model: type[models.Model], chain: frozenset[type[models.Model]]) -> tuple[str, ...]:
    organization = apps.get_model("rbac", "Organization")
    relation_fields = [field for field in model._meta.concrete_fields if field.is_relation]

    own_org = tuple(
        field.attname for field in relation_fields if field.related_model is organization
    )
    if own_org:
        return own_org
    if len(chain) > _MAX_OWNER_HOPS:
        return ()

    reference_fields = getattr(model, "soft_delete_reference_fields", ())
    paths: list[str] = []
    for field in relation_fields:
        owner = field.related_model
        if (
            field.remote_field.on_delete is not models.CASCADE
            or field.name in reference_fields
            or owner in chain
        ):
            continue
        paths.extend(f"{field.name}__{path}" for path in _org_paths(owner, chain | {owner}))
    return tuple(paths)


class CascadeOrgGuard:
    """Refuses a delete whose cascade would change a row of another organization than its root's."""

    def __init__(
        self,
        org_id: int | None,
        root_description: str,
        using: str | None = None,
        *,
        log_refusal: bool = True,
    ):
        """Guard a delete of the rows `root_description` names, all of organization `org_id`.

        Build one through for_root() or per_org(), which resolve the organization,
        unless the caller already knows it (a storage row's `org_id`). An `org_id` of
        None turns the guard off.
        """
        self.org_id = org_id
        self.root_description = root_description
        self.using = using
        self.log_refusal = log_refusal

    @classmethod
    def for_root(cls, root: models.Model, using: str | None = None) -> CascadeOrgGuard:
        """Guard a delete starting from `root`, in the organization owning it.

        Raises:
            CrossOrgCascadeError: `root` itself belongs to two organizations (a link
                row whose owners are in different organizations).
        """
        model = type(root)
        root_description = f"{model.__name__} {root.pk}"
        paths = org_paths(model)
        if all("__" not in path for path in paths):
            values = [getattr(root, path) for path in paths]
        else:
            values = list(
                model._base_manager.using(using).filter(pk=root.pk).values_list(*paths).first()
                or ()
            )
        org_id = _only_org(values, root_description, model, root.pk)
        return cls(org_id, root_description, using)

    @classmethod
    def per_org(
        cls,
        model: type[models.Model],
        pks: list,
        using: str | None = None,
        *,
        log_refusal: bool = True,
    ) -> list[tuple[CascadeOrgGuard, list]]:
        """Split rows of `model` by the organization owning each, for a delete of them all.

        Returns one guard per organization with the pks of its rows; rows without an
        organization share a guard that is off. Pks no longer in the table are left
        out. One query, none for a model with no path to an organization.

        Raises:
            CrossOrgCascadeError: A row belongs to two organizations.
        """
        paths = org_paths(model)
        if paths:
            rows = model._base_manager.using(using).filter(pk__in=pks).values_list("pk", *paths)
        else:
            rows = [(pk,) for pk in pks]
        pks_per_org: dict[int | None, list] = {}
        for pk, *values in rows:
            org_id = _only_org(values, f"{model.__name__} {pk}", model, pk, log_refusal)
            pks_per_org.setdefault(org_id, []).append(pk)
        return [
            (
                cls(org_id, _rows_description(model, org_pks), using, log_refusal=log_refusal),
                org_pks,
            )
            for org_id, org_pks in pks_per_org.items()
        ]

    def check_reverse_relation(self, parent: models.Model, relation: Any) -> None:
        """Refuse when a row pointing at `parent` through `relation` is another organization's.

        A path through the field the row points at `parent` with leads to `parent`'s
        organization, already checked when `parent` was reached, so only the row's
        other paths are looked up: one query, and none at all for a row owned only
        through `parent` (a flow's nodes).

        Raises:
            CrossOrgCascadeError: Such a row exists.
        """
        if self.org_id is None:
            return
        field_name = relation.field.name
        paths = [
            path
            for path in org_paths(relation.related_model)
            if path.split("__", 1)[0] != field_name
        ]
        if not paths:
            return
        rows = relation.related_model._base_manager.using(self.using).filter(**{field_name: parent})
        self._refuse_foreign_rows(rows, paths)

    def check_incoming_links(self, links: QuerySet, source_field_name: str, source_model) -> None:
        """Refuse when a many-to-many link about to be removed comes from another organization's row.

        `links` are rows of an auto-created through table; `source_field_name` is its
        foreign key to the row holding the link.

        Raises:
            CrossOrgCascadeError: Such a link exists.
        """
        if self.org_id is None:
            return
        paths = [f"{source_field_name}__{path}" for path in org_paths(source_model)]
        if paths:
            self._refuse_foreign_rows(links, paths)

    def check_collected(self, collector: Collector) -> None:
        """Refuse when a row Django's Collector would delete or update is another organization's.

        One query per model to delete, per fast-delete queryset and per field update.

        Raises:
            CrossOrgCascadeError: Such a row exists.
        """
        if self.org_id is None:
            return
        for model, instances in collector.data.items():
            self._refuse_foreign_instances(model, instances)
        for fast_delete in collector.fast_deletes:
            self._refuse_foreign_rows(fast_delete, org_paths(fast_delete.model))
        for (field, _value), batches in collector.field_updates.items():
            for batch in batches:
                if isinstance(batch, QuerySet):
                    self._refuse_foreign_rows(batch, org_paths(batch.model))
                else:
                    self._refuse_foreign_instances(field.model, batch)

    def _refuse_foreign_instances(self, model, instances) -> None:
        paths = org_paths(model)
        if paths:
            pks = [instance.pk for instance in instances]
            self._refuse_foreign_rows(
                model._base_manager.using(self.using).filter(pk__in=pks), paths
            )

    def _refuse_foreign_rows(self, rows: QuerySet, paths) -> None:
        if not paths:
            return
        foreign = Q()
        for path in paths:
            foreign |= Q(**{f"{path}__isnull": False}) & ~Q(**{path: self.org_id})
        offending = rows.filter(foreign).values_list("pk", *paths).first()
        if offending is not None:
            pk, *orgs = offending
            _refuse(
                self.root_description,
                self.org_id,
                rows.model,
                pk,
                {org for org in orgs if org is not None},
                self.log_refusal,
            )


def _only_org(values, root_description: str, model, pk, log_refusal: bool = True) -> int | None:
    """Return the one organization among a row's `values` (its org paths), None if none.

    Raises:
        CrossOrgCascadeError: The values name two organizations.
    """
    orgs = {value for value in values if value is not None}
    if len(orgs) > 1:
        _refuse(root_description, None, model, pk, orgs, log_refusal)
    return next(iter(orgs), None)


def _rows_description(model, pks: list) -> str:
    if len(pks) == 1:
        return f"{model.__name__} {pks[0]}"
    return f"{len(pks)} {model.__name__} rows"


def _refuse(
    root_description: str, root_org: int | None, model, pk, orgs, log_refusal: bool
) -> None:
    if log_refusal:
        logger.error(
            "Refused to delete {root} of org {root_org}: the delete reaches "
            "{model} {pk} of org(s) {orgs}, linked across organizations outside the API",
            root=root_description,
            root_org=root_org,
            model=model.__name__,
            pk=pk,
            orgs=sorted(orgs),
        )
    raise CrossOrgCascadeError()
