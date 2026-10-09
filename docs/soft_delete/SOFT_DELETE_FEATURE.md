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

`DJANGO_RECYCLE_BIN_RETENTION_DAYS` (required; `30` in `src/env.yaml` and `src/.env.example`, read into `settings.RECYCLE_BIN_RETENTION_DAYS`) sets how long a binned item stays before it is purged for good. It is declared in `src/env.yaml`, `src/.env.example` and `src/docker-compose.yaml`.

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

## 5. The Soft-Delete Roots

These models use `SoftDeleteMixin` (their `.delete()` goes to the recycle bin and they have `purge()`). Every one but `GraphVersion` has a bin tab, listed in `tables/services/recycle_bin/registry.py` (`bin_resources()`):

| Model | File |
|---|---|
| `Graph` | `tables/models/graph_models.py` |
| `GraphVersion` | `tables/models/graph_models.py` |
| `SourceCollection` | `tables/models/knowledge_models/collection_models.py` |
| `PythonCodeTool` | `tables/models/python_models.py` |
| `McpTool` | `tables/models/mcp_models.py` |
| `AgentDefinition` | `agents/models/agent_models.py` |
| `Surface` | `agents/models/surface_models.py` |
| `KeyValueTable` | `tables/models/key_value_models.py` |
| `Secret` | `tables/models/secret_models.py` |
| `RealtimeChannel` | `tables/models/webhook_models.py` |
| `WebhookTrigger` | `tables/models/webhook_models.py` |

Everything else that participates in soft delete (nodes, edges, condition groups, surface attachments, RAG documents, a voice channel's `TwilioChannel`, a trigger's ngrok/localhost config, etc.) uses `SoftDeleteFields` only, and is soft-deleted purely as a side effect of a root's cascade.

**Restore names.** A restore renames a root whose name was taken meanwhile (`name #2`). A `WebhookTrigger` path is unique across all organizations and can't hold spaces or `#`, so it gets `path-2` instead, checked against every org's live paths. A `RealtimeChannel` name isn't unique and never changes. A Twilio phone number can't be renamed: if a live channel took it meanwhile, the restored channel comes back without one, and its bin row warns about that first.

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

**Hidden relations (`related_name="+"`):** `_get_reverse_relations` walks hidden reverse relations too (`include_hidden=True`); `_get_related_objects` fetches every relation's rows with a direct queryset through the related model's base manager, so binned rows are included. The hidden reverse FKs of Django's auto-created M2M through tables are skipped: their rows are M2M links (next paragraph).

**Rows already in the bin:** `SET_NULL`/`SET_DEFAULT`/`SET(...)` also reach binned rows, so a restored row never points at something deleted while it was binned. A `CASCADE` child that was binned earlier on its own is marked visited and not walked into again; it keeps its own batch.

**M2M:** a deleted row keeps its own links (a flow's labels, a node's surfaces, a task's context tasks), so a restore brings them back. At the end of the call, `finish()` removes links that point at a binned row from live rows, in one query per relation; links from any binned row stay. M2M fields with an explicit `through=` model are real rows and follow the normal rules.

**Kept references:** a root that other rows *use* (a `Secret`, a `WebhookTrigger`, a `RealtimeChannel`) sets `soft_delete_keeps_references = True`. Deleting it then leaves the `SET_NULL` / `SET_DEFAULT` / `SET(...)` links and the incoming M2M links that point at it untouched, so a restore brings everything back working. While it's binned, every lookup through `objects` treats it as missing: `SecretResolver` only reads live secrets, so a binned secret never decrypts. Its encrypted value stays in the table until the purge. A purge (Django's Collector) clears the links. A forward FK still reads the binned row, because it goes through the base manager, so code that follows one checks `active` (`TwilioChannel.validate_provider`, `WebhookTrigger.get_active_config`, the Telegram registration, the Twilio post-save handler).

**Reference links:** a link model can list FK names in `soft_delete_reference_fields` (e.g. `("python_tool",)` on the surface tool links, `("collection",)` on the surface knowledge links, `("naive_rag",)` on `AgentNaiveRag`). A delete arriving through one of them means the link only *points at* the deleted row, so `finish()` hard-deletes the link: restoring a tool never re-links the surfaces that used it. A delete arriving through the link's owner FK bins it with the owner, so it comes back on restore. A link reached both ways in one call stays in the batch. Unlike M2M links, a reference link is removed even when its owner is already in the bin: deleting a tool permanently edits flows that are binned at that moment, which come back from a restore without that tool.

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
