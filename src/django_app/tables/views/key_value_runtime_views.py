from rbac.access.gates import IsSystemApiKeyAuthenticated
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from tables.exceptions import KeyValueSessionNotActiveError, KeyValueTableNotFoundError
from tables.models import KeyValueTable, Session
from tables.serializers.model_serializers.key_value_serializers import (
    KeyValueKeysSerializer,
    KeyValueWriteSerializer,
)
from tables.services.key_value_table_service import KeyValueTableService

_ACTIVE_STATUSES = (
    Session.SessionStatus.PENDING,
    Session.SessionStatus.RUN,
    Session.SessionStatus.WAIT_FOR_USER,
)


class KeyValueRuntimeAPIView(APIView):
    """Crew's read/write/delete path. The SYSTEM key is superadmin, so this view carries
    the org scoping itself: org comes from the session, never from the caller."""

    permission_classes = [IsSystemApiKeyAuthenticated]
    service = KeyValueTableService()

    def post(self, request, session_id: int, table_id: int, operation: str):
        session = self._get_active_session(session_id)
        table = self._get_accessible_table(session, table_id)

        if operation == "write":
            serializer = KeyValueWriteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            entries = serializer.validated_data["entries"]
            created = self.service.write(table, entries, session=session)
            return Response({"written": len(entries), "created": created, "table_name": table.name})

        serializer = KeyValueKeysSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        keys = serializer.validated_data["keys"]
        if operation == "read":
            return Response({"values": self.service.read(table, keys), "table_name": table.name})
        return Response({"deleted": self.service.delete(table, keys), "table_name": table.name})

    def _get_active_session(self, session_id: int) -> Session:
        session = Session.objects.select_related("graph").filter(pk=session_id).first()
        if session is None or session.graph is None:
            raise NotFound(f"Session {session_id} not found.")
        if session.status not in _ACTIVE_STATUSES:
            raise KeyValueSessionNotActiveError(session_id)
        return session

    def _get_accessible_table(self, session: Session, table_id: int) -> KeyValueTable:
        table = KeyValueTable.objects.filter(pk=table_id, org_id=session.graph.org_id).first()
        if table is None or not self.service.session_can_access(session, table):
            raise KeyValueTableNotFoundError(table_id)
        return table
