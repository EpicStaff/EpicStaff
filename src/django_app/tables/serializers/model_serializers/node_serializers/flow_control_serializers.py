from rest_framework import serializers
from django.db import transaction

from tables.serializers.model_serializers.python_serializers import PythonCodeSerializer
from tables.models.graph_models import (
    Condition,
    ConditionGroup,
    ConditionalEdge,
    DecisionTableNode,
    EndNode,
    GraphOrganization,
    StartNode,
)
from tables.serializers.base_serializer import (
    BaseGraphEntityMixin,
    ContentHashWritableMixin,
)
from tables.serializers.utils.mixins import NestedPythonCodeMixin
from tables.services.persistent_variables_service import (
    PersistentVariablesService,
)
from tables.constants.variables_constants import (
    DOMAIN_VARIABLES_KEY,
    DOMAIN_ORGANIZATION_KEY,
    DOMAIN_USER_KEY,
    DOMAIN_PERSISTENT_KEY,
)


class ConditionalEdgeSerializer(
    ContentHashWritableMixin, NestedPythonCodeMixin, serializers.ModelSerializer
):
    python_code = PythonCodeSerializer()

    class Meta(BaseGraphEntityMixin.Meta):
        model = ConditionalEdge
        fields = "__all__"


class StartNodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    node_name = serializers.SerializerMethodField(read_only=True)

    class Meta(BaseGraphEntityMixin.Meta):
        model = StartNode
        fields = [
            "id",
            "graph",
            "variables",
            "node_name",
        ] + BaseGraphEntityMixin.Meta.common_fields
        read_only_fields = ["node_name"]

    def get_node_name(self, obj):
        return "__start__"

    @transaction.atomic
    def update(self, instance, validated_data):
        old_variables = instance.variables.copy() if instance.variables else {}

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # TODO: rbac refactor
        graph_organization = GraphOrganization.objects.filter(
            graph=instance.graph
        ).first()

        if graph_organization:
            service = PersistentVariablesService()
            service.sync_graph_organization(
                graph_organization, old_variables, instance.variables
            )

        return instance

    # TODO: refactor, persistant variables story
    def validate(self, attrs):
        variables = attrs.get("variables")
        actual_variables = variables.get(DOMAIN_VARIABLES_KEY, {})

        persistent_variables = variables.get(DOMAIN_PERSISTENT_KEY, {})
        organization_variables = persistent_variables.get(DOMAIN_ORGANIZATION_KEY, [])
        user_variables = persistent_variables.get(DOMAIN_USER_KEY, [])

        service = PersistentVariablesService()
        for path in organization_variables + user_variables:
            value = service.get_by_path(actual_variables, path)
            if value is None:
                raise serializers.ValidationError(
                    f"Path {path} in {DOMAIN_PERSISTENT_KEY} does not exist in {DOMAIN_VARIABLES_KEY}."
                )

        return super().validate(attrs)


class EndNodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    node_name = serializers.SerializerMethodField(read_only=True)

    class Meta(BaseGraphEntityMixin.Meta):
        model = EndNode
        fields = [
            "id",
            "graph",
            "output_map",
            "node_name",
        ] + BaseGraphEntityMixin.Meta.common_fields
        read_only_fields = ["node_name"]

    def get_node_name(self, obj):
        return "__end_node__"


class ConditionSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    condition_group = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Condition
        fields = "__all__"


class ConditionGroupSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    conditions = ConditionSerializer(many=True, required=False)
    decision_table_node = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = ConditionGroup
        fields = "__all__"


class DecisionTableNodeSerializer(
    ContentHashWritableMixin, serializers.ModelSerializer
):
    condition_groups = ConditionGroupSerializer(many=True, required=False)

    class Meta:
        model = DecisionTableNode
        fields = "__all__"
