from rest_framework import serializers

from tables.models import Graph
from tables.models.graph_models import GraphNote
from tables.serializers.utils.soft_delete_fields import ExcludeSoftDeleteFieldsMixin
from tables.validators.note_metadata import drop_invalid_note_color


class GraphNoteImportSerializer(ExcludeSoftDeleteFieldsMixin, serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(queryset=Graph.objects.all(), write_only=True)

    class Meta:
        model = GraphNote
        exclude = ["created_at", "updated_at", "created_by"]

    def validate_metadata(self, value):
        # Normalized rather than rejected: an old export or snapshot must still import
        # or restore, with the note on its default colour.
        return drop_invalid_note_color(value)
