# Soft Delete Feature Documentation

## Architecture and System-Level Reference for Developers

This document covers the EpicStaff soft-delete mechanism: the `SOFT_DELETE` feature flag, the `SoftDeleteFields`/`SoftDeleteMixin` model mixins, the `ActiveManager`/`all_objects` manager pair, and the `DeleteService` cascade engine.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [The `SOFT_DELETE` Setting](#2-the-soft_delete-setting)
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

Deleting a `Graph`, `GraphVersion`, `SourceCollection`, or `PythonCodeTool` does not necessarily remove rows from the database. When `SOFT_DELETE` is enabled, `.delete()` on one of these roots marks the row (and every soft-delete-capable row it cascades into) as `is_soft_deleted=True` instead of issuing a real `DELETE`. This lets deleted flows/collections/tools be recovered, audited, or referenced by historical data (e.g. session snapshots) without the referential-integrity headaches of undoing a hard delete.

When `SOFT_DELETE` is disabled, `.delete()` on the same roots performs a genuine hard delete, and the database's own `on_delete` behavior (real `CASCADE`, `SET_NULL`, etc.) takes over exactly as it would without this feature.

## 2. The `SOFT_DELETE` Setting

Read once at Django startup in `src/django_app/django_app/settings.py`:

```python
SOFT_DELETE = os.getenv("SOFT_DELETE", "False").lower() in ("true", "1", "yes", "on")
```

Default is `False` — soft delete is opt-in. It's read from the environment in three places that must be kept consistent for a given deployment:

- `src/django_app/django_app/settings.py` — the Python-level default (`False`).
- `src/docker-compose.yaml` — `SOFT_DELETE: ${SOFT_DELETE:-False}` for the `django_app` service.
- `src/.env.example` — the template new deployments copy (`SOFT_DELETE=False`).
- `src/.dev.env` — the local dev environment explicitly opts in with `SOFT_DELETE=True`, since soft-delete behavior is what the team develops/tests against day to day.

`SoftDeleteMixin.delete()` (see below) is the only place that reads `settings.SOFT_DELETE`; everything else in the mechanism is agnostic to the flag.

## 3. Model Mixins

Both live in `src/django_app/tables/models/base_models.py`.

### SoftDeleteFields

```python
class SoftDeleteFields(models.Model):
    is_soft_deleted = models.BooleanField(default=False, db_default=False)
    soft_deleted_at = models.DateTimeField(null=True, blank=True)

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [...]  # is_soft_deleted/soft_deleted_at consistency, see §8
```

This is the **fields-only** mixin: it adds the two tracking columns and the two managers, but does **not** override `delete()`. A model that only inherits `SoftDeleteFields` (not `SoftDeleteMixin`) always performs a normal, unconditional Django hard delete when `.delete()` is called directly on an instance — regardless of `SOFT_DELETE`. It only ever gets soft-deleted when it's reached as a *dependent* of a `SoftDeleteMixin` root's cascade (see §6): `DeleteService` explicitly flips its flags and writes them, bypassing the (nonexistent) `delete()` override.

Use `SoftDeleteFields` for every node/child model that should participate in a soft-delete cascade but is never deleted directly by application code (nodes, edges, condition groups, surface attachments, etc. — essentially every non-root model in the graph/agent/knowledge domain).

### SoftDeleteMixin

```python
class SoftDeleteMixin(SoftDeleteFields):
    def delete(self, using=None, keep_parents=False):
        if settings.SOFT_DELETE:
            return self.soft_delete(using)
        return self.hard_delete(using, keep_parents)

    def soft_delete(self, using=None):
        from tables.services.soft_delete import DeleteService
        return DeleteService.delete(self, using=using)

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)
```

This is the **entry-point** mixin: `.delete()` on an instance branches on `SOFT_DELETE` and either delegates to `DeleteService` (soft path) or falls back to Django's normal `Model.delete()` (hard path, real DB `CASCADE`/`SET_NULL`/etc. apply). Use `SoftDeleteMixin` only on the 4 roots (§5) — the models application code actually calls `.delete()` on directly.

## 4. Managers

- **`objects` (`ActiveManager`)** — the default manager on every `SoftDeleteFields`/`SoftDeleteMixin` model. Filters `is_soft_deleted=False, soft_deleted_at__isnull=True`. Every "normal" query (`Model.objects.filter(...)`, REST API querysets, admin list views) only sees active rows through this manager.
- **`all_objects` (plain `models.Manager`)** — unfiltered, sees every row including soft-deleted ones. Used when code genuinely needs to reach a soft-deleted row: e.g. freeing up a UUID held by a soft-deleted `Graph` during import (`tables/import_export/strategies/graph.py`), or `DeleteService`'s own batched cascade writes (see §7 for why it's also the model's `base_manager`).

## 5. The 4 Soft-Delete Roots

Only these 4 models use `SoftDeleteMixin` (i.e., their `.delete()` actually branches on `SOFT_DELETE`):

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

**Batching:** all rows reached through a single reverse relation that resolve to rule 6 are soft-deleted with one `UPDATE ... WHERE pk IN (...)` instead of one `.save()` per row. Recursion into each row's own descendants (further reverse relations + M2M) still happens per-object, exactly as before batching was introduced — only the terminal `is_soft_deleted`/`soft_deleted_at` write is batched. Cycle-safety (a `visited` set keyed by `(model_class, pk)`) is unchanged.

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
        models.Q(is_soft_deleted=False, soft_deleted_at__isnull=True)
        | models.Q(is_soft_deleted=True, soft_deleted_at__isnull=False)
    ),
    name="%(app_label)s_%(class)s_soft_delete_consistency",
)
```

This rejects any row where `is_soft_deleted` and `soft_deleted_at` disagree (e.g. a stray `.update(is_soft_deleted=True)` that forgets to also set `soft_deleted_at`), including writes that bypass `DeleteService` entirely.

## 9. Key Files

- `src/django_app/tables/models/base_models.py` — `SoftDeleteFields`, `SoftDeleteMixin`, `ActiveManager`.
- `src/django_app/tables/services/soft_delete.py` — `DeleteService`, `_DeleteContext` (the cascade engine).
- `src/django_app/django_app/settings.py` — `SOFT_DELETE` flag definition.
- `src/django_app/tables/models/graph_models.py` — `Graph`, `GraphVersion` roots + the majority of `SoftDeleteFields` node/edge models.
- `src/django_app/tables/models/knowledge_models/collection_models.py` — `SourceCollection` root.
- `src/django_app/tables/models/python_models.py` — `PythonCodeTool` root.
- `src/django_app/tests/services_tests/test_soft_delete_cascade.py` — cascade behavior test suite (per-root full cascade, hard-delete path, PROTECT/RESTRICT/DO_NOTHING guards, forward-FK exclusions).
