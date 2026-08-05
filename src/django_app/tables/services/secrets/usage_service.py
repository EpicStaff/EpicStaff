"""Aggregates the UsageHit stream into the two Secret Usage surfaces.

Both public methods read the same registry, so the count shown on the secrets
list and the total shown in the usage dialog are the same arithmetic rather than
two implementations that happen to agree.
"""

from tables.models import Secret
from tables.services.secrets.usage_sources import (
    CATEGORY_FLOWS,
    CATEGORY_ORDER,
    USAGE_SOURCES,
    UsageHit,
)


def _resource_key(*, hit: UsageHit):
    """The identity `total` counts by.

    A flow counts once regardless of how many of its nodes reference the secret;
    everything else counts by display name. These are exactly the rules summary()
    renders, which is what makes usage_count always equal the detail total.
    """
    if hit.category == CATEGORY_FLOWS:
        return (CATEGORY_FLOWS, hit.resource_id)
    return (hit.category, hit.resource_name)


class SecretUsageService:
    """Answers "what breaks if I delete this secret?" for one organization."""

    def counts(self, *, org_id: int) -> dict[int, int]:
        """secret_id -> number of distinct resources referencing it.

        Every secret in the org gets an entry, including 0 for unused ones. A
        sparse dict would push a .get(id, 0) into the serializer, where a missing
        key and a genuine zero become indistinguishable — so a bug in _collect
        would silently render as "unused", the dangerous direction for a deletion
        guard.
        """
        secret_names = self._secret_names(org_id=org_id)
        hits = self._collect(org_id=org_id, secret_names=secret_names)

        resources: dict[int, set] = {
            secret_id: set() for secret_id in secret_names.values()
        }
        for hit in hits:
            resources[hit.secret_id].add(_resource_key(hit=hit))

        return {secret_id: len(keys) for secret_id, keys in resources.items()}

    def summary(self, *, secret: Secret) -> dict:
        """The usage payload for one secret.

        The org comes from secret.org_id, so this cannot be called with a
        mismatched secret/org pair. Only this secret's name is passed to the
        sources, so they narrow to it in SQL rather than sweeping the org and
        filtering afterwards.
        """
        hits = self._collect(
            org_id=secret.org_id, secret_names={secret.name: secret.pk}
        )

        categories = []
        for key in CATEGORY_ORDER:
            category = self._category(key=key, hits=hits)
            if category is not None:
                categories.append(category)

        return {
            "total": sum(len(category["items"]) for category in categories),
            "categories": categories,
        }

    def _category(self, *, key: str, hits: list[UsageHit]) -> dict | None:
        """One category, or None when it has no items.

        A category is emitted only when it has something in it. That is also why
        the frontend's ngrok_config and voice_twilio never appear — nothing
        produces hits for them, because those credentials are still plaintext
        CharFields rather than Secrets.
        """
        relevant = [hit for hit in hits if hit.category == key]
        if not relevant:
            return None

        items = (
            self._flow_items(hits=relevant)
            if key == CATEGORY_FLOWS
            else self._named_items(hits=relevant)
        )
        return {"key": key, "items": items}

    @staticmethod
    def _flow_items(*, hits: list[UsageHit]) -> list[dict]:
        """One item per flow, carrying its secret-using nodes.

        Nodes dedupe on (name, type): a decision table using the secret in both its
        pre- and post-computation blocks is two sources but one node, and the
        dialog must list it once.
        """
        flows: dict[int, dict] = {}
        for hit in hits:
            flow = flows.setdefault(
                hit.resource_id,
                {"id": hit.resource_id, "name": hit.resource_name, "nodes": []},
            )
            node = {"name": hit.node_name, "node_type": hit.node_type}
            if node not in flow["nodes"]:
                flow["nodes"].append(node)
        return list(flows.values())

    @staticmethod
    def _named_items(*, hits: list[UsageHit]) -> list[dict]:
        """One item per distinct display name.

        Deduped because these items carry nothing but a name and the dialog tracks
        by it, so duplicates make Angular raise NG0955. Collisions are reachable
        three ways: RealtimeConfig and RealtimeTranscriptionConfig have no per-org
        uniqueness on custom_name at all; four different config models fold into the
        single llm_configs category, where per-model constraints cannot prevent a
        clash; and a built-in PythonCodeTool (org=NULL) may share a name with an
        org-owned one.

        The cost is a documented under-count: two distinct resources with the same
        name are reported as one. Rendering them separately is impossible while the
        item shape is {name} alone, so the alternative would be inventing a
        disambiguating suffix the frontend never asked for.
        """
        names: list[str] = []
        for hit in hits:
            if hit.resource_name not in names:
                names.append(hit.resource_name)
        return [{"name": name} for name in names]

    @staticmethod
    def _secret_names(*, org_id: int) -> dict[str, int]:
        """name -> id for the org.

        Unambiguous because Secret has UniqueConstraint(org, name).
        """
        return dict(Secret.objects.filter(org_id=org_id).values_list("name", "id"))

    @staticmethod
    def _collect(*, org_id: int, secret_names: dict[str, int]) -> list[UsageHit]:
        """Every hit every registered source can see.

        Takes org_id explicitly and never resolves the org itself. Returns early
        for an org with no secrets so none of the twelve source queries run.
        """
        if not secret_names:
            return []

        hits: list[UsageHit] = []
        for source in USAGE_SOURCES:
            hits.extend(source.collect(org_id=org_id, secret_names=secret_names))
        return hits


secret_usage_service = SecretUsageService()


class SecretUsageCountProvider:
    """Computes every secret's usage count once, then serves lookups.

    A SerializerMethodField runs per row, so without this the list endpoint would
    repeat the whole source sweep once per secret. The viewset puts one of these in
    the serializer context per request; the first lookup computes and the rest are
    dict hits.
    """

    def __init__(self, *, org_id: int):
        self._org_id = org_id
        self._counts: dict[int, int] | None = None

    def count_for(self, *, secret_id: int) -> int:
        """Indexed directly on purpose.

        counts() enumerates every secret in the org, so an absent key means the
        service is broken. A KeyError says so loudly instead of rendering a broken
        sweep as "unused" — the dangerous direction for a deletion guard.
        """
        if self._counts is None:
            self._counts = secret_usage_service.counts(org_id=self._org_id)
        return self._counts[secret_id]
