from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema
from rbac.access.gates import IsSystemApiKeyAuthenticated
from rbac.models import Organization, OrganizationUser
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from src.shared.models import UserAction

from user_audit.actor import Actor
from user_audit.recorder import record_user_action
from user_audit.targets import TargetDescription

# What the chat service may record: the changes an operator makes to a desk.
CHAT_DESK_ACTIONS = (
    UserAction.CREATED,
    UserAction.UPDATED,
    UserAction.RENAMED,
    UserAction.DELETED,
    UserAction.PAUSED,
    UserAction.RESUMED,
    UserAction.KEY_ROTATED,
)
DESK_TARGET_TYPE = "desk"
# The chat service's limit for a desk name.
DESK_NAME_MAX_LENGTH = 255


class ServiceUserActionSerializer(serializers.Serializer):
    actor_user_id = serializers.IntegerField(min_value=1)
    org_id = serializers.IntegerField(min_value=1)
    action = serializers.ChoiceField(choices=[action.value for action in CHAT_DESK_ACTIONS])
    target_type = serializers.ChoiceField(choices=[DESK_TARGET_TYPE])
    target_id = serializers.CharField(max_length=64)
    target_name = serializers.CharField(max_length=DESK_NAME_MAX_LENGTH)
    previous_name = serializers.CharField(
        max_length=DESK_NAME_MAX_LENGTH, required=False, allow_null=True, default=None
    )


class ServiceUserActionView(APIView):
    """Records a user's action that another service (the chat service) carried out.

    The system key is superadmin, so this view checks the org itself: the actor must be an
    active user who may act in the active org the body names (`_actor_in_org`), or the
    answer is 404. The actor's email is read here, never taken from the caller.
    """

    permission_classes = [IsSystemApiKeyAuthenticated]

    @extend_schema(
        summary="Record a user action another service carried out",
        description="System API key only. Records a chat desk change in the org's user-action "
        "audit trail, under the user who made it.",
        request=ServiceUserActionSerializer,
        responses={204: None},
    )
    def post(self, request):
        serializer = ServiceUserActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = _actor_in_org(data["actor_user_id"], data["org_id"])
        if user is None:
            raise NotFound("No such member in this organization.")
        record_user_action(
            action=data["action"],
            org_id=data["org_id"],
            target_description=TargetDescription(
                type=data["target_type"], id=data["target_id"], name=data["target_name"]
            ),
            previous_name=data["previous_name"],
            actor=Actor(user_id=user.pk, email=user.email, api_key_name=None),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


def _actor_in_org(user_id: int, org_id: int):
    """The active user who may act in the active org `org_id`, else None.

    Matches `OrgContextService`: a member of the org, or a superadmin, who may act in any
    active org without being a member.
    """
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if user is None or not Organization.objects.filter(pk=org_id, is_active=True).exists():
        return None
    if user.is_superadmin or OrganizationUser.objects.filter(user=user, org_id=org_id).exists():
        return user
    return None
