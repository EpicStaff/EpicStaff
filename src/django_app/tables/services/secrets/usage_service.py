from collections import defaultdict
from dataclasses import dataclass

from tables.models import Secret
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.secrets.usage_sources import (
    CATEGORY_FLOWS,
    CATEGORY_ORDER,
    HITS_ASSEMBLERS,
    READABLE_NEVER,
    SHAPE_PROJECTIONS,
    USAGE_SOURCES,
    UsageHit,
)


@dataclass(frozen=True)
class UsageCounts:
    """How many resources referencing one secret the caller may and may not see."""

    readable: int
    hidden: int


class SecretUsageService:
    """Answers "what breaks if I delete this secret?" for one organization."""

    def counts(
        self, *, org_id: int, effective, secret_ids: set[int] | None = None
    ) -> dict[int, UsageCounts]:
        """secret_id -> readable/hidden counts of distinct resources referencing it."""
        if secret_ids is None:
            secret_ids = self._secret_ids(org_id=org_id)
        if not secret_ids:
            return {}

        readable_types = self.readable_types(effective=effective)
        first, *rest = [
            source.count_pairs(
                org_id=org_id,
                secret_ids=secret_ids,
                readability=source.readability(
                    readable_types=readable_types, org_id=org_id
                ),
            )
            for source in USAGE_SOURCES
        ]

        readable_keys: dict[int, set] = defaultdict(set)
        hidden_keys: dict[int, set] = defaultdict(set)
        for secret_id, usage_key, is_readable in first.union(*rest):
            bucket = readable_keys if is_readable else hidden_keys
            bucket[secret_id].add(usage_key)

        return {
            secret_id: UsageCounts(
                readable=len(readable_keys[secret_id]),
                hidden=len(hidden_keys[secret_id] - readable_keys[secret_id]),
            )
            for secret_id in secret_ids
        }

    def count_for(self, *, secret: Secret, effective) -> UsageCounts:
        """One secret's counts, in a single query."""
        return self.counts(
            org_id=secret.org_id, effective=effective, secret_ids={secret.pk}
        )[secret.pk]

    @staticmethod
    def readable_types(*, effective) -> frozenset[str]:
        """Every resource type the caller holds READ on."""
        return frozenset(
            resource_type.value
            for resource_type in ResourceType
            if effective.can(resource_type.value, Permission.READ)
        )

    def summary(self, *, secret: Secret, effective) -> dict:
        """The usage payload for one secret, limited to resources the caller may read."""
        readable_types = self.readable_types(effective=effective)
        hits = self._collect(
            org_id=secret.org_id,
            secret_ids={secret.pk},
            readable_types=readable_types,
        )

        categories = []
        for key in CATEGORY_ORDER:
            category = self._category(key=key, hits=hits)
            if category is not None:
                categories.append(category)

        counts = self.count_for(secret=secret, effective=effective)
        return {
            "readable_total": sum(len(category["items"]) for category in categories),
            "hidden_total": counts.hidden,
            "categories": categories,
        }

    def _category(self, *, key: str, hits: list[UsageHit]) -> dict | None:
        """One category, or None when it has no items."""
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
        """One item per flow, carrying its secret-using nodes."""
        flows: dict[int, dict] = {}
        for hit in hits:
            flow = flows.setdefault(
                hit.resource_id,
                {"id": hit.resource_id, "name": hit.resource_name, "nodes": []},
            )
            node = {
                "name": hit.node_name,
                "node_type": hit.node_type,
                "code_field": hit.code_field,
            }
            if node not in flow["nodes"]:
                flow["nodes"].append(node)

        for flow in flows.values():
            flow["nodes"].sort(
                key=lambda node: (
                    node["name"] or "",
                    node["node_type"],
                    node["code_field"] or "",
                )
            )
        return sorted(flows.values(), key=lambda flow: (flow["name"] or "", flow["id"]))

    @staticmethod
    def _named_items(*, hits: list[UsageHit]) -> list[dict]:
        """One item per distinct resource type and display name."""
        return [
            {"name": name, "type": resource_type}
            for resource_type, name in sorted(
                {(hit.resource_type, hit.resource_name) for hit in hits},
                key=lambda item: (item[1], item[0]),
            )
        ]

    @staticmethod
    def _secret_ids(*, org_id: int) -> set[int]:
        """Every secret id in the org."""
        return set(Secret.objects.filter(org_id=org_id).values_list("id", flat=True))

    @staticmethod
    def _collect(
        *, org_id: int, secret_ids: set[int], readable_types: frozenset[str]
    ) -> list[UsageHit]:
        """Every readable hit, in one query per column shape."""
        if not secret_ids:
            return []

        by_shape: dict[str, list] = defaultdict(list)
        for source in USAGE_SOURCES:
            readability = source.readability(
                readable_types=readable_types, org_id=org_id
            )
            if readability == READABLE_NEVER:
                continue
            by_shape[source.detail_shape].append((source, readability))

        hits: list[UsageHit] = []
        for shape, entries in by_shape.items():
            projection = SHAPE_PROJECTIONS[shape]
            querysets = [
                getattr(source, projection)(
                    org_id=org_id, secret_ids=secret_ids, readability=readability
                )
                for source, readability in entries
            ]
            first, *rest = querysets
            rows = first.union(*rest) if rest else first
            hits.extend(HITS_ASSEMBLERS[shape](rows=rows))
        return hits


secret_usage_service = SecretUsageService()
