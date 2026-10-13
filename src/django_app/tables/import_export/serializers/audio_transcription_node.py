from rest_framework import serializers

from tables.models import AudioTranscriptionNode, Graph
from tables.serializers.utils.mixins import ExecutionTimeoutSerializerMixin


class AudioTranscriptionNodeImportSerializer(
    ExecutionTimeoutSerializerMixin, serializers.ModelSerializer
):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(queryset=Graph.objects.all(), write_only=True)

    class Meta:
        model = AudioTranscriptionNode
        exclude = ["created_at", "updated_at", "created_by"]
