# Index setup

`runner.py` runs from `entrypoint.sh` on every `auditor` boot and creates
`audit_events` from `0001_create_audit_events_index.json` if it does not already
exist. Creating an index that exists is a safe no-op, so this is idempotent and
stays correct if `auditor` is ever scaled to N replicas.

OpenSearch has no migration concept, so the mapping file is versioned like one.

## Changing the mapping

* **Adding a field is additive and safe** - a plain `PUT _mapping` applies it to
  the live index.
* **Changing an existing field's type is not.** OpenSearch cannot reinterpret
  already-indexed data. It requires a new index, a `_reindex` (with a painless
  script if the shape changes, not just the type), and a swap. Never attempt an
  in-place type change; it will be rejected, and the runner will not notice the
  drift because the index already exists.

## Field format decisions

These are load-bearing for the filter/query layer, so they are recorded rather
than left to be rediscovered:

* **`error` is a flat string, not an object.** It was briefly `{"message": str}`
  purely because the model demanded a dict. An error is one human-readable
  message, and the primary pipeline's `ErrorMessageData.details` is already a
  bare `str(error)`.

* **`error` is `text` with an `error.raw` `wildcard` subfield**, and the two are
  not interchangeable:
  - `error` (analyzed `text`) - `match` / `match_phrase`, relevance-ranked.
  - `error.raw` (`wildcard` type) - `equals`, `starts_with`, `ends_with`,
    `contains`. Pass `case_insensitive: true` for the ci variants.

  Do **not** compile the Error filter's `contains` op to a `match` query. The
  standard analyzer treats a dot between letters as a word-joiner, so
  `"litellm.AuthenticationError: OpenAIException"` tokenizes to
  `["litellm.authenticationerror", "openaiexception", ...]` - a `match` for
  `AuthenticationError` finds nothing, because no such token exists. Verified
  against `_analyze` on a real litellm error.

  `error.raw` is deliberately the `wildcard` type rather than
  `keyword` + `ignore_above`. A `keyword` subfield silently stops indexing
  values past its `ignore_above` limit, which stack traces routinely exceed -
  every keyword-based op would then miss exactly the longest, most interesting
  errors with no error reported. The `wildcard` type has no such cap (verified
  on a 3000+ char value).

* **`event_time` is the field every time filter and the retention filter uses**,
  never `record_time`. `event_time` is when the thing happened (stamped by the
  emitting service); `record_time` is when `auditor` received it. They differ by
  the client's batch-flush interval.

* **Timestamps must be serialized by the model, not formatted ad hoc.**
  `record_time` was once `isoformat()`'d straight into the `_source` dict while
  `event_time` came through pydantic. Both are valid `date`s to OpenSearch, but
  they are different *strings* (`+00:00` vs `Z`), which put two UTC spellings in
  one document and leaked into the CSV/JSON export.

* **`auto_expand_replicas: "0-1"`, not `number_of_replicas: 1`.** On the
  single-node dev topology a replica can never be allocated, so a fixed count of
  1 left the index permanently `yellow` and made real health problems
  indistinguishable from that baseline. `0-1` resolves to 0 on one node and
  starts replicating automatically once a second node joins.

## `input`/`output`/`details` are `flat_object`, not dynamically-mapped `object`

Fixed after hitting it live: these three fields hold arbitrary session
payloads - including keys from user-authored python node code - and dynamic
`object` mapping has two failure modes that both actually occurred:

1. **Type lock.** OpenSearch locks a field's type from the *first* document it
   ever sees for that exact key path (e.g. `input.yesno`). A flow variable that
   starts as `{}` before its node runs and becomes a plain string once it does
   (a completely normal pattern) permanently breaks every later write to that
   path with a `mapper_parsing_exception` - silently, since the bulk API just
   reports a per-item error that's easy to miss. This dropped real audit events
   in production-shaped testing before the fix.
2. **Field-count growth.** Every new key becomes a new field in the index
   mapping; the default `index.mapping.total_fields.limit` is 1000, and a
   handful of dev sessions already produced ~100 dynamic fields this way.

`flat_object` (OpenSearch's name for what Elasticsearch calls `flattened`)
avoids both: it doesn't register per-key sub-fields at all, so there's nothing
to lock a type or blow the field-count limit. Trade-off: no native numeric
range queries on a nested key (e.g. `output.tokens > 500`) - that needs an
OpenSearch runtime field to cast the value at query time, or promoting a
specific hot key to its own real top-level typed field if it's queried often
enough to be worth a dedicated column.

Applied via a full index delete + recreate (dev-only migration path - no
production data existed yet to preserve). A real reindex+alias-swap migration
(see "Changing an existing field's type" above) is still the only safe path
once real data exists.
