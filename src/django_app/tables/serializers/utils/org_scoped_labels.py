from tables.serializers.org_scoped_fields import resolve_active_org_id


def org_scoped_label_ids(instance, request) -> list[int]:
    """Label ids on ``instance.labels`` visible to the requester's active org.

    Guards the read path for models whose ``labels`` M2M is a single relation
    shared across orgs on a hybrid-visible row (e.g. a built-in
    ``PythonCodeTool``/``McpTool`` with ``org=None``): without this, ``GET``
    would serialize every org's label ids attached to that shared row,
    leaking org-1's label id into org-2's response (EST-3773).
    """
    if request is None:
        return list(instance.labels.values_list("id", flat=True))
    org_id = resolve_active_org_id(request)
    return list(instance.labels.filter(org_id=org_id).values_list("id", flat=True))


def set_org_scoped_labels(instance, labels, request) -> None:
    """Replace only the active org's slice of ``instance.labels``, preserving
    every other org's attachment on the same row untouched.

    A naive ``instance.labels.set(labels)`` is a destructive full replace: on
    a shared built-in tool, org-2 submitting its own label ids would wipe
    org-1's previously-attached labels from the same M2M (EST-3773). The
    incoming ``labels`` are already guaranteed to belong to the active org —
    they were validated through ``OrgScopedPrimaryKeyRelatedField`` — so it is
    safe to treat everything else on the relation as "some other org's rows"
    and leave it alone.
    """
    if request is None:
        # Conservative fallback for contexts without a request in scope (e.g.
        # internal/test usage without serializer context) — org scope can't
        # be resolved, so fall back to a plain full replace.
        instance.labels.set(labels)
        return
    org_id = resolve_active_org_id(request)
    other_org_label_ids = list(
        instance.labels.exclude(org_id=org_id).values_list("pk", flat=True)
    )
    # `.set()` accepts a list of pks: other orgs' existing label ids, kept
    # as-is, plus this org's newly submitted label ids.
    instance.labels.set([*other_org_label_ids, *(label.pk for label in labels)])
