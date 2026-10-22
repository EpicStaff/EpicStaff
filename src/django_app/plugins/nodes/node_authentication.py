"""How a plugin node proves who it is: `Authorization: PluginNodeKey <PLUGINS_NODE_KEY>`.

Used only by the node API views. It is never one of DRF's default authentication classes,
so a node key authenticates nowhere else, and no other credential authenticates there. Like
a node-purpose service-account key, a node key works only through nginx's internal listener
on the plugins network, never through the development API listener (`internal_listener`).
"""

import hashlib
import hmac
from dataclasses import dataclass

from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission

from plugins.exceptions import NodeNotAuthenticatedError
from plugins.identity.internal_listener import came_through_internal_listener
from plugins.models import PluginNode

KEYWORD = "PluginNodeKey"


def node_key_hash(key: str) -> str:
    """The sha256 of a node key, as `PluginNode.key_hash` stores it."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PluginNodePrincipal:
    """`request.user` of a node request. Not a person: it holds no EpicStaff permission."""

    node: PluginNode
    is_authenticated: bool = True
    is_superadmin: bool = False


class PluginNodeAuthentication(BaseAuthentication):
    """Authenticate a node by its key; a missing or wrong key, or a request that did not come
    through the internal listener, is 401 `node_not_authenticated`."""

    def authenticate(self, request):
        if not came_through_internal_listener(request):
            raise NodeNotAuthenticatedError()
        scheme, _, key = request.META.get("HTTP_AUTHORIZATION", "").partition(" ")
        if scheme != KEYWORD or not key:
            raise NodeNotAuthenticatedError()
        presented = node_key_hash(key.strip())
        # Every node with a key is compared, in constant time, so the answer time does not
        # depend on how much of a guessed key matches. Key hashes are unique, so at most one
        # node matches.
        matches = [
            candidate
            for candidate in PluginNode.objects.filter(key_hash__isnull=False)
            if hmac.compare_digest(candidate.key_hash, presented)
        ]
        if len(matches) != 1:
            raise NodeNotAuthenticatedError()
        node = matches[0]
        return PluginNodePrincipal(node=node), node

    def authenticate_header(self, request) -> str:
        return KEYWORD


class IsPluginNode(BasePermission):
    def has_permission(self, request, view) -> bool:
        return isinstance(request.auth, PluginNode)
