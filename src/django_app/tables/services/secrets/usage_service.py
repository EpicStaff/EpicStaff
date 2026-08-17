from collections import defaultdict

from tables.models import Secret
from tables.services.secrets.usage_sources import (
    CATEGORY_FLOWS,
    CATEGORY_ORDER,
    HITS_ASSEMBLERS,
    SHAPE_PROJECTIONS,
    USAGE_SOURCES,
    UsageHit,
)


class SecretUsageService:
    """Answers "what breaks if I delete this secret?" for one organization."""

    def counts(
        self, *, org_id: int, secret_ids: set[int] | None = None
    ) -> dict[int, int]:
        """secret_id -> number of distinct resources referencing it."""
        if secret_ids is None:
            secret_ids = self._secret_ids(org_id=org_id)
        if not secret_ids:
            return {}

        first, *rest = [
            source.count_pairs(org_id=org_id, secret_ids=secret_ids)
            for source in USAGE_SOURCES
        ]

        counts = dict.fromkeys(secret_ids, 0)
        for secret_id, _ in first.union(*rest):
            counts[secret_id] += 1
        return counts

    def count_for(self, *, secret: Secret) -> int:
        """One secret's count, in a single query."""
        return self.counts(org_id=secret.org_id, secret_ids={secret.pk})[secret.pk]

    def summary(self, *, secret: Secret) -> dict:
        """The usage payload for one secret."""
        hits = self._collect(org_id=secret.org_id, secret_ids={secret.pk})

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
    def _collect(*, org_id: int, secret_ids: set[int]) -> list[UsageHit]:
        """Every hit every registered source can see, in one query per column shape."""
        if not secret_ids:
            return []

        by_shape: dict[str, list] = defaultdict(list)
        for source in USAGE_SOURCES:
            by_shape[source.detail_shape].append(source)

        hits: list[UsageHit] = []
        for shape, sources in by_shape.items():
            projection = SHAPE_PROJECTIONS[shape]
            first, *rest = [
                getattr(source, projection)(org_id=org_id, secret_ids=secret_ids)
                for source in sources
            ]
            rows = first.union(*rest) if rest else first
            hits.extend(HITS_ASSEMBLERS[shape](rows=rows))
        return hits


secret_usage_service = SecretUsageService()
