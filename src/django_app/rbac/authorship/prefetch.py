from django.contrib.auth import get_user_model
from django.db.models import Prefetch

from rbac.authorship.user_summary import USER_SUMMARY_FIELDS
from rbac.models.last_edit import ResourceLastEdit


def _author_prefetch(lookup: str) -> Prefetch:
    return Prefetch(lookup, queryset=get_user_model().objects.only(*USER_SUMMARY_FIELDS))


def _last_edits_prefetch(lookup: str) -> Prefetch:
    # Every last-edit column is read (content_type/object_id join the GenericRelation
    # back to its resource); only the joined editor is narrowed to its summary columns.
    own_fields = (field.name for field in ResourceLastEdit._meta.concrete_fields)
    editor_fields = (f"edited_by__{field}" for field in USER_SUMMARY_FIELDS)
    return Prefetch(
        lookup,
        queryset=ResourceLastEdit.objects.select_related("edited_by").only(
            *own_fields, *editor_fields
        ),
    )


def authorship_prefetches(
    prefix: str = "", *, author: bool = True, last_edit: bool = True
) -> list[Prefetch]:
    """Return the prefetches that render `created_by` and the last edit without a query per row.

    Args:
        prefix: Relation path from the queryset's model to the authored rows, e.g.
            `"python_node_list"`; empty for the queryset's own rows.
        author: Prefetch the `created_by` author.
        last_edit: Prefetch `last_edits` with the editor.
    """
    path = f"{prefix}__" if prefix else ""
    prefetches = []
    if author:
        prefetches.append(_author_prefetch(f"{path}created_by"))
    if last_edit:
        prefetches.append(_last_edits_prefetch(f"{path}last_edits"))
    return prefetches
