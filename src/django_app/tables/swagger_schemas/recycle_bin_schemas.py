from drf_spectacular.utils import OpenApiExample, OpenApiParameter

from tables.serializers.recycle_bin_serializers import (
    RecycleBinContentsSerializer,
    RecycleBinPageSerializer,
)
from tables.services.recycle_bin.bin_contents_service import CONTENTS_FILTERS
from tables.services.recycle_bin.bin_service import ENTRY_ORDERINGS
from tables.services.recycle_bin.presentation import NO_ACCESS

_NAMES_NEED_READ = (
    "Contents are named only when the user has READ on their resource type in the active org "
    "(an agent's surfaces need surfaces:read, a surface's tools tools:read). The others are "
    "only counted, per kind, in `hidden_contents`; `contents_total` counts everything a "
    f'restore brings back. A detail line naming such an item says "{NO_ACCESS}".'
)

RECYCLE_BIN_LIST_GET = {
    "summary": "List the recycle bin",
    "description": f"The active org's binned items of this resource, paged. {_NAMES_NEED_READ}",
    "request": None,
    "parameters": [
        OpenApiParameter("limit", int, description="Default 50, at most 100"),
        OpenApiParameter("offset", int),
        OpenApiParameter("search", str, description="Part of the item's name, in any case"),
        OpenApiParameter(
            "ordering", str, enum=list(ENTRY_ORDERINGS), description="Default: -deleted_at"
        ),
        OpenApiParameter(
            "contents",
            str,
            enum=list(CONTENTS_FILTERS),
            description="Only items whose restore brings back something (`some`) "
            "or nothing (`none`), as `contents_total` counts it",
        ),
    ],
    "responses": RecycleBinPageSerializer,
    "examples": [
        OpenApiExample(
            "An agent whose surfaces the user may not read",
            response_only=True,
            value={
                "count": 1,
                "next": None,
                "previous": None,
                "results": [
                    {
                        "id": 12,
                        "name": "Support agent",
                        "deleted_at": "2026-10-28T09:15:00Z",
                        "days_left": 6,
                        "details": [
                            {"label": "Created by", "value": None, "format": "user"},
                            {"label": "Deleted by", "value": None, "format": "user"},
                            {"label": "Description", "value": None, "format": "text"},
                            {"label": "Instructions", "value": None, "format": "text"},
                            {"label": "LLM", "value": None, "format": "text"},
                        ],
                        "contents": [],
                        "hidden_contents": [{"kind": "surface", "count": 2}],
                        "contents_total": 2,
                    }
                ],
            },
        )
    ],
}

RECYCLE_BIN_CONTENTS_GET = {
    "summary": "Show all of a binned item's contents",
    "description": "One binned item's contents, up to 5,000: \"Show all\" when the list's 100 "
    f"aren't enough. {_NAMES_NEED_READ}",
    "request": None,
    "responses": RecycleBinContentsSerializer,
}
