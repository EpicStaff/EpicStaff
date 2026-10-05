# Soft Delete Feature Documentation

## Architecture and System-Level Reference for Developers

This document covers the EpicStaff soft-delete mechanism (the recycle bin): the `SoftDeleteFields`/`SoftDeleteMixin` model mixins, the `objects`/`deleted_objects`/`all_objects` managers, and the `DeleteService` cascade engine, delete batches and `purge()`.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Batches and Retention](#2-batches-and-retention)
3. [Model Mixins](#3-model-mixins)
   - [SoftDeleteFields](#softdeletefields)
   - [SoftDeleteMixin](#softdeletemixin)
4. [Managers](#4-managers)
5. [The 4 Soft-Delete Roots](#5-the-4-soft-delete-roots)
6. [DeleteService Cascade Rules](#6-deleteservice-cascade-rules)
7. [Manager Configuration Per Model](#7-manager-configuration-per-model)
8. [Data Integrity](#8-data-integrity)
9. [Key Files](#9-key-files)

---

## 1. System Overview

Deleting a `Graph`, `GraphVersion`, `SourceCollection`, or `PythonCodeTool` never removes rows on its own. `.delete()` on one of these roots always marks the row (and every soft-delete-capable row it cascades into) as `active=False`, which moves it to the recycle bin. Deleted flows, collections and tools can then be restored, or referenced by historical data (e.g. session snapshots), without the referential-integrity headaches of undoing a hard delete.

A permanent delete is always explicit: `purge()` on a root removes it and its whole subtree through Django's normal `Model.delete()`, so the database's own `on_delete` behavior (real `CASCADE`, `SET_NULL`, etc.) applies. The recycle bin's "delete permanently" action and the retention cleanup use it.

## 2. Batches and Retention

Every `DeleteService.delete()` call creates one `soft_delete_batch` UUID and one timestamp and writes both to every row it bins, the root and its children alike. A restore brings back exactly the rows of one batch, never rows that were deleted on their own earlier. `DeleteService.delete()` returns the batch id, or `None` when the root was already in the bin; it locks the root first, so two concurrent deletes of the same item can't split a batch.

`DJANGO_RECYCLE_BIN_RETENTION_DAYS` (default `7`, read into `settings.RECYCLE_BIN_RETENTION_DAYS`) sets how long a binned item stays before it is purged for good. It is declared in `src/env.yaml`, `src/.env.example` and `src/docker-compose.yaml`.

## 3. Model Mixins

Both live in `src/django_app/tables/models/base_models.py`.

### SoftDeleteFields

```python
class SoftDeleteFields(models.Model):
    active = models.BooleanField(default=True, db_default=True)
    soft_deleted_at = models.DateTimeField(null=True, blank=True)

    objects = ActiveManager()
    deleted_objects = DeletedManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [...]  # active/soft_deleted_at consistency, see §8
```

This is the **fields-only** mixin: it adds the two tracking columns and the managers, but does **not** override `delete()`. A model that only inherits `SoftDeleteFields` (not `SoftDeleteMixin`) always performs a normal, unconditional Django hard delete when `.delete()` is called directly on an instance. It only ever gets soft-deleted when it's reached as a *dependent* of a `SoftDeleteMixin` root's cascade (see §6): `DeleteService` explicitly flips its flags and writes them, bypassing the (nonexistent) `delete()` override.

Use `SoftDeleteFields` for every node/child model that should participate in a soft-delete cascade but is never deleted directly by application code (nodes, edges, condition groups, surface attachments, etc. — essentially every non-root model in the graph/agent/knowledge domain).

### SoftDeleteMixin

```python
class SoftDeleteMixin(SoftDeleteFields):
    def delete(self, using=None, keep_parents=False):
        return self.soft_delete(using)

    def soft_delete(self, using=None):
        from tables.services.soft_delete import DeleteService

        return DeleteService.delete(self, using=using)

    def purge(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)
```

This is the **entry-point** mixin: `.delete()` on an instance always delegates to `DeleteService` and returns the batch id. `purge()` falls back to Django's normal `Model.delete()` (real DB `CASCADE`/`SET_NULL`/etc. apply); the Collector walks reverse relations through each model's base manager (`all_objects`), so it reaches rows already in the bin. Use `SoftDeleteMixin` only on the 4 roots (§5) — the models application code actually calls `.delete()` on directly.

## 4. Managers

- **`objects` (`ActiveManager`)** — the default manager on every `SoftDeleteFields`/`SoftDeleteMixin` model. Filters `active=True`. Every "normal" query (`Model.objects.filter(...)`, REST API querysets, admin list views, reverse accessors) only sees active rows through this manager.
- **`deleted_objects` (`DeletedManager`)** — filters `active=False`: the rows in the recycle bin.
- **`all_objects` (plain `models.Manager`)** — unfiltered, sees every row including soft-deleted ones. Used when code genuinely needs to reach a soft-deleted row: e.g. freeing up a UUID held by a soft-deleted `Graph` during import (`tables/import_export/strategies/graph.py`), or `DeleteService`'s own batched cascade writes (see §7 for why it's also the model's `base_manager`).

## 5. The 4 Soft-Delete Roots

Only these 4 models use `SoftDeleteMixin` (i.e., their `.delete()` goes to the recycle bin and they have `purge()`):

| Model | File |
|---|---|
| `Graph` | `tables/models/graph_models.py` |
| `GraphVersion` | `tables/models/graph_models.py` |
| `SourceCollection` | `tables/models/knowledge_models/collection_models.py` |
| `PythonCodeTool` | `tables/models/python_models.py` |

Everything else that participates in soft delete (nodes, edges, condition groups, surface attachments, RAG documents, etc.) uses `SoftDeleteFields` only, and is soft-deleted purely as a side effect of one of these 4 roots' cascade.

## 6. DeleteService Cascade Rules

`src/django_app/tables/services/soft_delete.py`. Entry point: `DeleteService.delete(obj, using=None)`, called by `SoftDeleteMixin.soft_delete()`. Runs inside `transaction.atomic(using=using)` — a `PROTECT`/`RESTRICT` anywhere in the subtree rolls back the whole cascade, leaving the root untouched.

Priority order per reverse relation (evaluated once per relation, not once per row — all rows reached through a given relation share the same target model and the same FK's `on_delete`):

1. **`PROTECT`** → raises `django.db.models.deletion.ProtectedError`.
2. **`RESTRICT`** → raises `django.db.models.deletion.RestrictedError`.
3. **`SET_NULL`** → the FK is nulled and saved.
4. **`SET_DEFAULT`** → the FK is set to its field default and saved.
5. **`SET(...)`** → the FK is set to the callable's return value and saved.
6. **SoftDeleteFields, any other `on_delete` (`CASCADE`, `DO_NOTHING`, or unrecognized)** → the dependent row(s) are soft-deleted (batched — see below) instead of following the FK's literal semantics.
7. **Not `SoftDeleteFields`, nullable field, still no sentinel matched** → nulled as a defensive fallback.
8. **`DO_NOTHING`** (not `SoftDeleteFields`, not nullable) → raises `ImproperlyConfigured` — `DeleteService` cannot guarantee referential integrity here.
9. **`CASCADE`** (not `SoftDeleteFields`) → real hard delete of the dependent row (`Model.delete()`, not `obj.delete()`, to bypass any `SoftDeleteFields`/`SoftDeleteMixin` override).

An explicit `PROTECT`/`RESTRICT`/`SET_NULL`/`SET_DEFAULT`/`SET(...)` on the FK is always a stronger, deliberate signal than "this model happens to support soft deletion", and wins over rule 6. SoftDeleteFields only overrides the default hard-delete/`CASCADE` behavior.

**Batching:** all rows reached through a single reverse relation that resolve to rule 6 are soft-deleted with one `UPDATE ... WHERE pk IN (...)` instead of one `.save()` per row. Recursion into each row's own descendants (further reverse relations + M2M) still happens per-object, exactly as before batching was introduced — only the terminal `active`/`soft_deleted_at` write is batched. Cycle-safety (a `visited` set keyed by `(model_class, pk)`) is unchanged.

**Hidden relations (`related_name="+"`):** `_get_reverse_relations` only sees non-hidden relations. A handful of `related_name="+"` fields exist in the schema deliberately (e.g. `SessionTrigger`'s snapshot FKs, which must survive node/graph deletion; `OrgScopedModel.created_by`, an audit trail) — see the docstring on `_get_reverse_relations` for the full audited list. Adding a new `related_name="+"` field whose target should participate in a cascade requires giving it a real `related_name`, or explicitly extending this method — don't assume hiding it is always safe.

**M2M:** clearing an M2M relationship only removes the join rows; the other side of the relationship is never deleted or soft-deleted.

## 7. Manager Configuration Per Model

Every concrete model built on `SoftDeleteFields`/`SoftDeleteMixin` declares, in its own `Meta`:

```python
class Meta:
    default_manager_name = "objects"
    base_manager_name = "all_objects"
```

This is necessary per-model, not just once on the abstract `SoftDeleteFields.Meta` — Django does not merge `Meta` options across multiple abstract base classes when a concrete model has more than one abstract ancestor (confirmed empirically: a concrete model with two abstract parents inherits `Meta` from only one of them, whichever "wins" the MRO lookup). Declaring it on every concrete `Meta` is the only reliable way to guarantee:

- **`default_manager_name = "objects"`** — ordinary querysets (`Model.objects.all()`, related-manager access, admin) stay active-only by default.
- **`base_manager_name = "all_objects"`** — Django's own internal machinery (the deletion `Collector`, some `prefetch_related` paths) uses the *unfiltered* manager, so it doesn't silently skip soft-deleted rows that legitimately still exist in the table.

Models with only a single abstract mixin still declare this explicitly for consistency and to guard against a future refactor accidentally introducing a second abstract base.

## 8. Data Integrity

`SoftDeleteFields.Meta` carries a `CheckConstraint` (templated per concrete model, since the mixin is abstract and reused by 60+ models):

```python
models.CheckConstraint(
    check=(
        models.Q(active=True, soft_deleted_at__isnull=True)
        | models.Q(active=False, soft_deleted_at__isnull=False)
    ),
    name="%(app_label)s_%(class)s_soft_delete_consistency",
)
```

This rejects any row where `active` and `soft_deleted_at` disagree (e.g. a stray `.update(active=False)` that forgets to also set `soft_deleted_at`), including writes that bypass `DeleteService` entirely.

## 9. Key Files

- `src/django_app/tables/models/base_models.py` — `SoftDeleteFields`, `SoftDeleteMixin`, `ActiveManager`, `DeletedManager`.
- `src/django_app/tables/services/soft_delete.py` — `DeleteService`, `_DeleteContext` (the cascade engine).
- `src/django_app/django_app/settings/base.py` — `RECYCLE_BIN_RETENTION_DAYS`.
- `src/django_app/tables/models/graph_models.py` — `Graph`, `GraphVersion` roots + the majority of `SoftDeleteFields` node/edge models.
- `src/django_app/tables/models/knowledge_models/collection_models.py` — `SourceCollection` root.
- `src/django_app/tables/models/python_models.py` — `PythonCodeTool` root.
- `src/django_app/tests/services_tests/test_soft_delete_cascade.py` — cascade behavior test suite (per-root full cascade, purge path, batches, PROTECT/RESTRICT/DO_NOTHING guards, forward-FK exclusions).
