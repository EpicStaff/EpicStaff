from rest_framework import serializers
from tables.models.tag_models import GraphTag


class GraphTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = GraphTag
        fields = "__all__"
