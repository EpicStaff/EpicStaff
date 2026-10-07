from rest_framework import serializers

from tables.models import KeyValueTable


class KeyValueTableImportSerializer(serializers.ModelSerializer):
    """A key-value table's definition. Its entries are org data and never travel in an export."""

    class Meta:
        model = KeyValueTable
        fields = ["id", "name", "description"]
