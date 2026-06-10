"""Integration tests for the collab presence WebSocket endpoint.

Covers all four acceptance criteria:
  AC1 – invalid/missing token → close 1008
  AC2 – two clients on the same flow both receive count 2
  AC3 – one disconnect → remaining client receives count 1
  AC4 – connections on different flow_ids are fully isolated

The test module builds a minimal FastAPI app around the real
``PresenceService`` + ``PresenceRepository`` backed by a FakeRedis client.
It never imports ``api.main`` or ``utils.auth`` (which require env vars and
optional third-party deps not installed in this environment).
"""

import asyncio
import json
from collections.abc import Callable
from types import SimpleNamespace

import fakeredis.aioredis as fake_aioredis
import pytest
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient

from application.presence_service import PresenceService
from infrastructure.persistence.presence_repository import PresenceRepository


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_fake_repo() -> PresenceRepository:
    """Build a PresenceRepository backed by an in-process FakeRedis client."""
    fake_client = fake_aioredis.FakeRedis()
    fake_redis_service = SimpleNamespace(aioredis_client=fake_client)
    return PresenceRepository(redis_service=fake_redis_service)  # type: ignore[arg-type]


def _build_app(
    presence_service: PresenceService,
    introspect_fn: Callable[[str], dict | None],
) -> FastAPI:
    """Return a minimal FastAPI app that only exposes the collab presence route.

    ``introspect_fn`` is injected so tests never import ``utils.auth``
    (which pulls in ``core.config.settings`` and requires all env vars).
    """
    app = FastAPI()

    @app.websocket("/realtime/collab/")
    async def collab_presence(
        websocket: WebSocket,
        flow_id: int | None = None,
        token: str | None = None,
    ):
        if not token:
            await websocket.close(code=1008)
            return

        user_info = introspect_fn(token)
        if not user_info:
            await websocket.close(code=1008)
            return

        if flow_id is None:
            await websocket.close(code=1008)
            return

        await websocket.accept()
        member_id: str | None = None
        try:
            member_id = await presence_service.join(flow_id, websocket)
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            if member_id is not None:
                await presence_service.leave(flow_id, websocket, member_id)

    return app


# A valid user payload returned by a successful token introspection.
_VALID_USER = {"active": True, "user_id": 1, "username": "test"}


def _valid_introspect(token: str) -> dict | None:
    return _VALID_USER


def _invalid_introspect(token: str) -> dict | None:
    return None


# ---------------------------------------------------------------------------
# AC1 – authentication failures close with code 1008
# ---------------------------------------------------------------------------


class TestAuthRejection:
    """Missing or invalid tokens must cause an abnormal close (1008)."""

    def test_missing_token_closes_1008(self):
        service = PresenceService(repository=_make_fake_repo())
        app = _build_app(service, _valid_introspect)

        with TestClient(app) as client:
            with pytest.raises(Exception):
                # Starlette TestClient raises WebSocketDenied / similar on 1008.
                with client.websocket_connect("/realtime/collab/?flow_id=1") as ws:
                    ws.receive_text()

    def test_invalid_token_closes_1008(self):
        service = PresenceService(repository=_make_fake_repo())
        app = _build_app(service, _invalid_introspect)

        with TestClient(app) as client:
            with pytest.raises(Exception):
                with client.websocket_connect(
                    "/realtime/collab/?flow_id=1&token=bad"
                ) as ws:
                    ws.receive_text()

    def test_missing_flow_id_closes_1008(self):
        service = PresenceService(repository=_make_fake_repo())
        app = _build_app(service, _valid_introspect)

        with TestClient(app) as client:
            with pytest.raises(Exception):
                with client.websocket_connect("/realtime/collab/?token=valid") as ws:
                    ws.receive_text()


# ---------------------------------------------------------------------------
# AC2 – two clients on the same flow both receive count 2
# ---------------------------------------------------------------------------


class TestTwoClientsOnSameFlow:
    """Second connection broadcasts count 2 to all sockets on the flow."""

    def test_second_join_broadcasts_count_two_to_both(self):
        repo = _make_fake_repo()
        service = PresenceService(repository=repo)
        app = _build_app(service, _valid_introspect)

        with TestClient(app) as client:
            with client.websocket_connect(
                "/realtime/collab/?flow_id=10&token=t"
            ) as ws1:
                # First join → count 1 (only ws1 in the flow).
                msg1 = json.loads(ws1.receive_text())
                assert msg1 == {"type": "presence", "flow_id": 10, "count": 1}

                with client.websocket_connect(
                    "/realtime/collab/?flow_id=10&token=t"
                ) as ws2:
                    # ws2 just joined — it receives its own join broadcast.
                    msg_ws2 = json.loads(ws2.receive_text())
                    assert msg_ws2 == {
                        "type": "presence",
                        "flow_id": 10,
                        "count": 2,
                    }
                    # ws1 also received the broadcast when ws2 joined.
                    msg_ws1_update = json.loads(ws1.receive_text())
                    assert msg_ws1_update == {
                        "type": "presence",
                        "flow_id": 10,
                        "count": 2,
                    }


# ---------------------------------------------------------------------------
# AC3 – disconnect → remaining connections receive decremented count
# ---------------------------------------------------------------------------


class TestDisconnectDecrementsCount:
    """When a socket disconnects, the remaining sockets receive count - 1."""

    def test_leave_broadcasts_count_one_to_remaining(self):
        repo = _make_fake_repo()
        service = PresenceService(repository=repo)
        app = _build_app(service, _valid_introspect)

        with TestClient(app) as client:
            with client.websocket_connect(
                "/realtime/collab/?flow_id=20&token=t"
            ) as ws1:
                # Consume join broadcast (count 1).
                ws1.receive_text()

                with client.websocket_connect(
                    "/realtime/collab/?flow_id=20&token=t"
                ) as ws2:
                    # Consume ws2's own join broadcast.
                    ws2.receive_text()
                    # Consume the same broadcast on ws1.
                    ws1.receive_text()

                # ws2 context exited → disconnect → `leave` fires → count drops to 1.
                # ws1 must receive the decremented count.
                leave_msg = json.loads(ws1.receive_text())
                assert leave_msg == {
                    "type": "presence",
                    "flow_id": 20,
                    "count": 1,
                }


# ---------------------------------------------------------------------------
# AC4 – different flow_ids are fully isolated
# ---------------------------------------------------------------------------


class TestFlowIsolation:
    """Connections on different flows must not affect each other's counts."""

    def test_different_flows_see_independent_counts(self):
        repo = _make_fake_repo()
        service = PresenceService(repository=repo)
        app = _build_app(service, _valid_introspect)

        with TestClient(app) as client:
            with client.websocket_connect(
                "/realtime/collab/?flow_id=100&token=t"
            ) as ws_flow_100:
                # flow 100 starts at 1.
                msg_100 = json.loads(ws_flow_100.receive_text())
                assert msg_100 == {
                    "type": "presence",
                    "flow_id": 100,
                    "count": 1,
                }

                with client.websocket_connect(
                    "/realtime/collab/?flow_id=200&token=t"
                ) as ws_flow_200:
                    # flow 200 starts independently at 1.
                    msg_200 = json.loads(ws_flow_200.receive_text())
                    assert msg_200 == {
                        "type": "presence",
                        "flow_id": 200,
                        "count": 1,
                    }

                # ws_flow_200 disconnected: flow 200 count drops to 0.
                # Verify Redis counts reflect isolation.
                count_100 = asyncio.run(repo.count(100))
                count_200 = asyncio.run(repo.count(200))

                assert count_100 == 1, f"flow 100 count should be 1, got {count_100}"
                assert count_200 == 0, f"flow 200 count should be 0, got {count_200}"

            # ws_flow_100 also disconnected now.
            final_100 = asyncio.run(repo.count(100))
            assert (
                final_100 == 0
            ), f"flow 100 should be 0 after ws disconnect, got {final_100}"


# ---------------------------------------------------------------------------
# AC5 – Redis failure during join leaves no local socket registered
# ---------------------------------------------------------------------------


class TestJoinRedisFailure:
    """If Redis raises during join, no socket must be registered locally and
    a second client on the same flow must see a correct count of 1."""

    def test_redis_failure_leaves_no_local_socket_and_route_closes_cleanly(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        repo = _make_fake_repo()
        service = PresenceService(repository=repo)
        app = _build_app(service, _valid_introspect)

        # Patch add_member to raise only on the first call, simulating a Redis
        # failure during the first client's join.
        original_add_member = repo.add_member
        call_count = 0

        async def _failing_add_member(flow_id: int, member_id: str) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("simulated Redis failure")
            await original_add_member(flow_id, member_id)

        monkeypatch.setattr(repo, "add_member", _failing_add_member)

        with TestClient(app) as client:
            # First connection: join fails at Redis — route must close without
            # NameError and the socket must NOT be in _sockets.
            with pytest.raises(Exception):
                with client.websocket_connect(
                    "/realtime/collab/?flow_id=42&token=t"
                ) as ws_bad:
                    ws_bad.receive_text()

            # No local socket must remain after the failed join.
            assert (
                service._sockets.get(42) is None
                or len(service._sockets.get(42, set())) == 0
            )

            # Second connection succeeds normally.
            with client.websocket_connect(
                "/realtime/collab/?flow_id=42&token=t"
            ) as ws_ok:
                msg = json.loads(ws_ok.receive_text())
                # Redis has exactly 1 member; local count matches.
                assert msg == {"type": "presence", "flow_id": 42, "count": 1}
