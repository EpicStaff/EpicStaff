from rbac.access.gates import IsSystemApiKeyAuthenticated
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from tables.exceptions import PersistenceSessionNotActiveError, PersistenceTableNotFoundError
from tables.models import PersistenceTable, Session
from tables.serializers.model_serializers.persistence_serializers import (
    PersistenceKeysSerializer,
    PersistenceWriteSerializer,
)
from tables.services.persistence_table_service import PersistenceTableService

_ACTIVE_STATUSES = (
    Session.SessionStatus.PENDING,
    Session.SessionStatus.RUN,
    Session.SessionStatus.WAIT_FOR_USER,
)


class PersistenceRuntimeAPIView(APIView):
    """Crew's read/write/delete path. The SYSTEM key is superadmin, so this view carries
    the org scoping itself: org comes from the session, never from the caller."""

    permission_classes = [IsSystemApiKeyAuthenticated]
    service = PersistenceTableService()

    def post(self, request, session_id: int, table_id: int, operation: str):
        session = self._get_active_session(session_id)
        table = self._get_accessible_table(session, table_id)

        if operation == "write":
            serializer = PersistenceWriteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            written = self.service.write(
                table, serializer.validated_data["entries"], session=session
            )
            return Response({"written": written})

        serializer = PersistenceKeysSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        keys = serializer.validated_data["keys"]
        if operation == "read":
            return Response({"values": self.service.read(table, keys)})
        return Response({"deleted": self.service.delete(table, keys)})

    def _get_active_session(self, session_id: int) -> Session:
        session = Session.objects.select_related("graph").filter(pk=session_id).first()
        if session is None or session.graph is None:
            raise NotFound(f"Session {session_id} not found.")
        if session.status not in _ACTIVE_STATUSES:
            raise PersistenceSessionNotActiveError(session_id)
        return session

    def _get_accessible_table(self, session: Session, table_id: int) -> PersistenceTable:
        table = PersistenceTable.objects.filter(pk=table_id, org_id=session.graph.org_id).first()
        if table is None or not self.service.session_can_access(session, table):
            raise PersistenceTableNotFoundError(table_id)
        return table
