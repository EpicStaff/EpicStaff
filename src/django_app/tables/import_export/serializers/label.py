from rest_framework import serializers
from tables.models.label_models import Label


class LabelImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Label
        fields = ["id", "name", "parent", "metadata"]
