"""What a plugin's backend asks EpicStaff about itself and about people: `/api/plugin-runtime/`.

Reached only with a service-account key (through the plugins network), never with a
person's credentials. The organization is the service account's own: a request naming
another one in `X-Organization-Id` gets 404. Counted by the service account's request rate
like every other call it makes; never recorded as activity, as nothing changes.
"""

from rbac.access.org_context import OrgContextService
from rest_framework.response import Response
from rest_framework.views import APIView

from plugins.access.people_service import PluginPeopleService
from plugins.identity.service_account_authentication import (
    IsPluginServiceAccount,
    PluginServiceAccountAuthentication,
)
from plugins.serializers.runtime_api import (
    PeopleLookupRequestSerializer,
    people_lookup_response,
    plugin_person,
    service_account_info,
)


class PluginRuntimeView(APIView):
    authentication_classes = [PluginServiceAccountAuthentication]
    permission_classes = [IsPluginServiceAccount]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        OrgContextService().resolve(request=request, view_kwargs={})

    @property
    def grant(self):
        return self.request.auth.service_account.grant


class ServiceAccountMeView(PluginRuntimeView):
    def get(self, request):
        return Response(service_account_info(request.auth, request.user))


class PluginPersonView(PluginRuntimeView):
    def get(self, request, user_id: int):
        facts = PluginPeopleService().person(self.grant, user_id)
        return Response(plugin_person(facts).model_dump(mode="json"))


class PeopleLookupView(PluginRuntimeView):
    def post(self, request):
        body = PeopleLookupRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        people = PluginPeopleService().people(self.grant, body.validated_data["user_ids"])
        return Response(people_lookup_response(people))
