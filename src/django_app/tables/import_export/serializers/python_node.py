from rest_framework import serializers

from tables.models import Graph, PythonNode, PythonCode
from tables.import_export.serializers.python_tools import PythonCodeImportSerializer


class PythonNodeImportSerializer(serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(
        queryset=Graph.objects.all(), write_only=True
    )
    python_code = PythonCodeImportSerializer(read_only=True)
    python_code_id = serializers.PrimaryKeyRelatedField(
        queryset=PythonCode.objects.all(),
        source="python_code",
        write_only=True,
    )

    class Meta:
        model = PythonNode
        exclude = ["created_at", "updated_at"]
