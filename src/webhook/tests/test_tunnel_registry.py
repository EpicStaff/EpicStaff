import asyncio
import os

import pytest
from loguru import logger
from src.shared.models import (
    LocalhostConfigData,
    NgrokConfigData,
    WebhookConfigData,
    WebhookTriggerAuthData,
)
from pyngrok.exception import PyngrokNgrokError
from redis.exceptions import ConnectionError as RedisConnectionError
from transport_secrets import seal, sealing_cryptographer

from app.core.settings import settings
from app.services.tunnel_registry import (
    ConfigsFailedToRegisterError,
    UnavailableWebhookPathError,
    UnregisteredWebhookPathError,
)


async def _published_tunnel_urls(redis_service) -> dict[str, str]:
    """The tunnel URLs Django reads to show each webhook's public address."""
    return await redis_service.client.hgetall(settings.TUNNEL_URLS_HASH_KEY)


@pytest.mark.parametrize(
    ("domain", "expected_url"),
    [
        ("my-local.dev", "http://my-local.dev"),
        (None, f"http://{settings.LOCALHOST_TARGET_HOST}:{settings.LOCALHOST_TARGET_PORT}"),
    ],
    ids=["custom-domain", "target-host-and-port"],
)
async def test_localhost_tunnel_url_is_published_and_removed_on_unregister(
    tunnel_registry, redis_service, domain, expected_url
):
    config = LocalhostConfigData(name="hook", org_id=1, domain=domain)

    await tunnel_registry.register(config)

    assert await _published_tunnel_urls(redis_service) == {config.unique_id: expected_url}

    await tunnel_registry.unregister(config.unique_id)

    assert await _published_tunnel_urls(redis_service) == {}


async def test_ngrok_tunnel_is_started_with_its_config_and_fully_torn_down(
    tunnel_registry, redis_service, ngrok_environment
):
    config = NgrokConfigData(
        name="hook",
        org_id=1,
        auth_token=seal("secret-token"),
        domain="my.ngrok.app",
        region="us",
    )

    await tunnel_registry.register(config)

    connect_call = ngrok_environment.ngrok.connect.call_args
    # nginx's tunnel listener, which serves only /webhooks/ and /voice/: never port 80, which is
    # the whole of EpicStaff and would be published on the tunnel's public URL.
    assert connect_call.args == ("epicstaff-nginx:8083", "http")
    assert connect_call.kwargs["domain"] == "my.ngrok.app"
    pyngrok_config = connect_call.kwargs["pyngrok_config"]
    assert pyngrok_config.auth_token == "secret-token"
    assert pyngrok_config.region == "us"
    assert await _published_tunnel_urls(redis_service) == {
        config.unique_id: "https://real-ngrok-url.com"
    }

    await tunnel_registry.unregister(config.unique_id)

    ngrok_environment.ngrok.disconnect.assert_called_once_with(
        "https://real-ngrok-url.com", pyngrok_config=pyngrok_config
    )
    ngrok_environment.process.kill_process.assert_called_once_with(pyngrok_config.ngrok_path)
    assert not os.path.exists(pyngrok_config.ngrok_path)
    assert list(ngrok_environment.temp_root.iterdir()) == []
    assert await _published_tunnel_urls(redis_service) == {}


@pytest.mark.parametrize(
    "auth_token", ["plain-ngrok-token", "gAAAAAforged-ngrok-token"], ids=["plaintext", "forged"]
)
async def test_ngrok_config_whose_token_cannot_be_decrypted_is_not_registered(
    tunnel_registry, redis_service, ngrok_environment, auth_token
):
    """Its error names the config, never the token, and the other configs still sync."""
    broken = NgrokConfigData(name="broken", org_id=1, auth_token=auth_token)
    healthy = LocalhostConfigData(name="healthy", org_id=1)
    logged: list[str] = []
    sink_id = logger.add(logged.append, format="{message}")
    try:
        with pytest.raises(ConfigsFailedToRegisterError) as raised:
            await tunnel_registry.register_many(
                WebhookConfigData(ngrok_configs=[broken], localhost_configs=[healthy])
            )
    finally:
        logger.remove(sink_id)

    assert raised.value.failed_ids == [broken.unique_id]
    ngrok_environment.ngrok.connect.assert_not_called()
    assert set(await _published_tunnel_urls(redis_service)) == {healthy.unique_id}
    [error_line] = [line for line in logged if broken.unique_id in line]
    assert "could not be decrypted" in error_line
    assert all(auth_token not in line for line in logged)


def _ngrok_config(auth_token: str) -> NgrokConfigData:
    return NgrokConfigData(name="hook", org_id=1, auth_token=auth_token)


async def _sync(tunnel_registry, config: NgrokConfigData) -> None:
    await tunnel_registry.register_many(WebhookConfigData(ngrok_configs=[config]))


async def test_resealing_the_same_ngrok_token_does_not_restart_the_tunnel(
    tunnel_registry, ngrok_environment
):
    """Django seals the token afresh on every publish; only a new token is a change."""
    first = _ngrok_config(seal("same-token"))
    resealed = _ngrok_config(seal("same-token"))
    assert first.auth_token != resealed.auth_token

    await _sync(tunnel_registry, first)
    await _sync(tunnel_registry, resealed)

    assert ngrok_environment.ngrok.connect.call_count == 1


async def test_a_rotated_ngrok_token_restarts_the_tunnel_with_the_new_token(
    tunnel_registry, ngrok_environment
):
    await _sync(tunnel_registry, _ngrok_config(seal("old-token")))
    await _sync(tunnel_registry, _ngrok_config(seal("new-token")))

    assert ngrok_environment.ngrok.connect.call_count == 2
    restarted_config = ngrok_environment.ngrok.connect.call_args.kwargs["pyngrok_config"]
    assert restarted_config.auth_token == "new-token"


async def test_an_undecryptable_ngrok_token_takes_the_restart_path_and_fails_loudly(
    tunnel_registry, ngrok_environment
):
    forged_token = "gAAAAAforged-ngrok-token"
    await _sync(tunnel_registry, _ngrok_config(seal("old-token")))
    logged: list[str] = []
    sink_id = logger.add(logged.append, format="{message}")
    try:
        with pytest.raises(ConfigsFailedToRegisterError):
            await _sync(tunnel_registry, _ngrok_config(forged_token))
    finally:
        logger.remove(sink_id)

    assert any("changed. Restarting" in line for line in logged)
    assert any("Error registering" in line and "could not be decrypted" in line for line in logged)
    assert all(forged_token not in line for line in logged)
    assert ngrok_environment.ngrok.connect.call_count == 1


async def test_an_ngrok_restart_with_a_token_ngrok_rejects_fails_closed(
    tunnel_registry, redis_service, ngrok_environment
):
    """A revoked token decrypts fine; only ngrok refuses it, when the tunnel starts. The
    config must then fail to register like an undecryptable one, not be served by a
    tunnel that never came up while the closed tunnel's URL stays published."""
    hook = NgrokConfigData(
        name="hook", org_id=1, auth_token=seal("valid-token"), auth=_hook_auth("old-secret")
    )
    await tunnel_registry.register_many(WebhookConfigData(ngrok_configs=[hook]))
    ngrok_environment.ngrok.connect.side_effect = PyngrokNgrokError(
        "The ngrok process errored on start: authentication failed: The authtoken you "
        "specified is properly formed, but it is invalid. ERR_NGROK_107"
    )
    revoked = hook.model_copy(
        update={"auth_token": seal("revoked-token"), "auth": _hook_auth("new-secret")}
    )
    logged = []
    sink_id = logger.add(logged.append, level="WARNING", format="{message}")
    try:
        with pytest.raises(ConfigsFailedToRegisterError) as raised:
            await tunnel_registry.register_many(WebhookConfigData(ngrok_configs=[revoked]))
        await tunnel_registry.republish_tunnel_urls()
    finally:
        logger.remove(sink_id)

    assert raised.value.failed_ids == [hook.unique_id]
    assert await _path_answer(tunnel_registry, "hook") == "unavailable"
    assert await _published_tunnel_urls(redis_service) == {}
    [failure] = [
        message.record for message in logged if hook.unique_id in message.record["message"]
    ]
    assert failure["level"].name == "ERROR"
    assert "ERR_NGROK_107" in failure["message"]
    # Neither tunnel lingers: the old one is closed, and the failed start leaves no ngrok
    # process or working directory behind.
    ngrok_environment.ngrok.disconnect.assert_called_once()
    assert list(ngrok_environment.temp_root.iterdir()) == []


def _localhost_config(sealed_secret: str) -> LocalhostConfigData:
    auth = WebhookTriggerAuthData(
        kind="webhook", header_name="EPICSTAFF_API_KEY", secret=sealed_secret
    )
    return LocalhostConfigData(name="hook", org_id=1, auth=auth)


async def _sync_logged(tunnel_registry, config: LocalhostConfigData) -> list[str]:
    logged: list[str] = []
    sink_id = logger.add(logged.append, format="{message}")
    try:
        await tunnel_registry.register_many(WebhookConfigData(localhost_configs=[config]))
    finally:
        logger.remove(sink_id)
    return logged


async def test_resealing_the_same_auth_secret_is_not_an_auth_update(tunnel_registry):
    """Django reseals the secret on every publish; that alone must not count as a change."""
    first = _localhost_config(seal("hook-secret"))
    await _sync_logged(tunnel_registry, first)

    logged = await _sync_logged(tunnel_registry, _localhost_config(seal("hook-secret")))

    assert not any("updated without tunnel restart" in line for line in logged)
    _, routed_config = await tunnel_registry.resolve_by_path("hook")
    assert routed_config.auth.secret == first.auth.secret


async def test_a_new_auth_secret_is_swapped_in_without_a_restart(tunnel_registry):
    await _sync_logged(tunnel_registry, _localhost_config(seal("old-secret")))
    rotated = _localhost_config(seal("new-secret"))

    logged = await _sync_logged(tunnel_registry, rotated)

    assert any("updated without tunnel restart" in line for line in logged)
    assert not any("changed. Restarting" in line for line in logged)
    _, routed_config = await tunnel_registry.resolve_by_path("hook")
    assert routed_config.auth.secret == rotated.auth.secret
    assert all("new-secret" not in line and rotated.auth.secret not in line for line in logged)


def _hook_auth(secret: str) -> WebhookTriggerAuthData:
    return WebhookTriggerAuthData(kind="webhook", header_name="X-Key", secret=seal(secret))


async def _routed_secret(tunnel_registry, path: str) -> str:
    _, config = await tunnel_registry.resolve_by_path(path)
    return sealing_cryptographer().decrypt(config.auth.secret)


async def test_a_failed_ngrok_restart_stops_serving_the_superseded_config_and_applies_the_rest(
    tunnel_registry, redis_service, ngrok_environment
):
    """A rotated token that cannot be used must not leave the old tunnel accepting the
    old auth secret; the other changes of the same set still apply."""
    hook = NgrokConfigData(
        name="hook", org_id=1, auth_token=seal("old-token"), auth=_hook_auth("old-secret")
    )
    rotated = LocalhostConfigData(name="rotated", org_id=1, auth=_hook_auth("old-secret"))
    deleted = LocalhostConfigData(name="deleted", org_id=1, auth=_hook_auth("secret"))
    await tunnel_registry.register_many(
        WebhookConfigData(ngrok_configs=[hook], localhost_configs=[rotated, deleted])
    )
    unusable_hook = hook.model_copy(
        update={"auth_token": "gAAAAAforged-ngrok-token", "auth": _hook_auth("new-secret")}
    )

    with pytest.raises(ConfigsFailedToRegisterError) as raised:
        await tunnel_registry.register_many(
            WebhookConfigData(
                ngrok_configs=[unusable_hook],
                localhost_configs=[
                    rotated.model_copy(update={"auth": _hook_auth("new-secret")})
                ],
            )
        )

    assert raised.value.failed_ids == [hook.unique_id]
    with pytest.raises(UnavailableWebhookPathError):
        await tunnel_registry.resolve_by_path("hook")
    ngrok_environment.ngrok.disconnect.assert_called_once()
    assert await _routed_secret(tunnel_registry, "rotated") == "new-secret"
    with pytest.raises(UnregisteredWebhookPathError):
        await tunnel_registry.resolve_by_path("deleted")
    assert set(await _published_tunnel_urls(redis_service)) == {rotated.unique_id}

    await tunnel_registry.register_many(
        WebhookConfigData(
            ngrok_configs=[unusable_hook.model_copy(update={"auth_token": seal("new-token")})],
            localhost_configs=[rotated.model_copy(update={"auth": _hook_auth("new-secret")})],
        )
    )

    assert await _routed_secret(tunnel_registry, "hook") == "new-secret"


async def test_a_failed_localhost_restart_stops_serving_the_superseded_config(
    tunnel_registry, redis_service, monkeypatch
):
    """A localhost tunnel fails to register when its URL cannot be published."""
    hook = LocalhostConfigData(
        name="hook", org_id=1, domain="old.local", auth=_hook_auth("old-secret")
    )
    await tunnel_registry.register_many(WebhookConfigData(localhost_configs=[hook]))
    moved_hook = hook.model_copy(update={"domain": "new.local", "auth": _hook_auth("new-secret")})
    publish_tunnel_url = redis_service.set_tunnel_url

    async def redis_down(unique_id: str, url: str) -> None:
        raise RedisConnectionError("Redis is down")

    monkeypatch.setattr(redis_service, "set_tunnel_url", redis_down)

    with pytest.raises(ConfigsFailedToRegisterError):
        await tunnel_registry.register_many(WebhookConfigData(localhost_configs=[moved_hook]))

    with pytest.raises(UnavailableWebhookPathError):
        await tunnel_registry.resolve_by_path("hook")

    monkeypatch.setattr(redis_service, "set_tunnel_url", publish_tunnel_url)
    await tunnel_registry.register_many(WebhookConfigData(localhost_configs=[moved_hook]))

    assert await _routed_secret(tunnel_registry, "hook") == "new-secret"
    assert await _published_tunnel_urls(redis_service) == {hook.unique_id: "http://new.local"}


async def test_a_failed_path_answers_unavailable_while_the_rest_of_the_set_registers(
    tunnel_registry, redis_service, ngrok_environment, monkeypatch
):
    """Registering a tunnel can take seconds; the path of a config that already failed
    must answer as unavailable meanwhile, not as unknown, or senders drop the URL."""
    hook = NgrokConfigData(
        name="hook", org_id=1, auth_token=seal("old-token"), auth=_hook_auth("old-secret")
    )
    await tunnel_registry.register_many(WebhookConfigData(ngrok_configs=[hook]))
    slow = LocalhostConfigData(name="slow", org_id=1, auth=_hook_auth("secret"))
    slow_registration_started = asyncio.Event()
    finish_slow_registration = asyncio.Event()
    publish_tunnel_url = redis_service.set_tunnel_url

    async def slow_publish(unique_id: str, url: str) -> None:
        if unique_id == slow.unique_id:
            slow_registration_started.set()
            await finish_slow_registration.wait()
        await publish_tunnel_url(unique_id, url)

    monkeypatch.setattr(redis_service, "set_tunnel_url", slow_publish)
    applying = asyncio.create_task(
        tunnel_registry.register_many(
            WebhookConfigData(
                ngrok_configs=[hook.model_copy(update={"auth_token": "gAAAAAforged-ngrok-token"})],
                localhost_configs=[slow],
            )
        )
    )
    try:
        await asyncio.wait_for(slow_registration_started.wait(), timeout=3)

        with pytest.raises(UnavailableWebhookPathError):
            await tunnel_registry.resolve_by_path("hook")
    finally:
        finish_slow_registration.set()
        with pytest.raises(ConfigsFailedToRegisterError):
            await applying

    assert await _routed_secret(tunnel_registry, "slow") == "secret"


async def _path_answer(tunnel_registry, path: str) -> str:
    """How a request to `path` is answered: the secret it is checked against, or why not."""
    try:
        return await _routed_secret(tunnel_registry, path)
    except UnregisteredWebhookPathError:
        return "unregistered"
    except UnavailableWebhookPathError:
        return "unavailable"


@pytest.mark.parametrize(
    ("next_configs", "expect_failure", "renamed_path_answer"),
    [
        (lambda failed: [], False, "unregistered"),
        (
            lambda failed: [
                failed.model_copy(update={"name": "renamed", "auth_token": seal("token")})
            ],
            False,
            "secret",
        ),
        (lambda failed: [failed.model_copy(update={"name": "renamed"})], True, "unavailable"),
    ],
    ids=["deleted-in-django", "renamed-and-fixed", "renamed-still-failing"],
)
async def test_the_path_of_a_failed_config_django_no_longer_has_is_unregistered(
    tunnel_registry, ngrok_environment, next_configs, expect_failure, renamed_path_answer
):
    failed = NgrokConfigData(
        name="hook", org_id=1, auth_token="gAAAAAforged-ngrok-token", auth=_hook_auth("secret")
    )
    with pytest.raises(ConfigsFailedToRegisterError):
        await tunnel_registry.register_many(WebhookConfigData(ngrok_configs=[failed]))

    next_set = WebhookConfigData(ngrok_configs=next_configs(failed))
    if expect_failure:
        with pytest.raises(ConfigsFailedToRegisterError):
            await tunnel_registry.register_many(next_set)
    else:
        await tunnel_registry.register_many(next_set)

    assert await _path_answer(tunnel_registry, "hook") == "unregistered"
    assert await _path_answer(tunnel_registry, "renamed") == renamed_path_answer


async def test_a_config_failing_on_every_sync_logs_one_error_then_warnings_with_the_attempt(
    tunnel_registry, ngrok_environment
):
    failing = NgrokConfigData(
        name="hook", org_id=1, auth_token="gAAAAAforged-ngrok-token", auth=_hook_auth("secret")
    )
    logged = []
    sink_id = logger.add(logged.append, level="WARNING", format="{message}")
    try:
        for _ in range(3):
            with pytest.raises(ConfigsFailedToRegisterError):
                await tunnel_registry.register_many(WebhookConfigData(ngrok_configs=[failing]))
        # Registered once, so its next failure is a new one.
        await tunnel_registry.register_many(
            WebhookConfigData(
                ngrok_configs=[failing.model_copy(update={"auth_token": seal("token")})]
            )
        )
        with pytest.raises(ConfigsFailedToRegisterError):
            await tunnel_registry.register_many(WebhookConfigData(ngrok_configs=[failing]))
    finally:
        logger.remove(sink_id)

    failures = [
        (message.record["level"].name, message.record["message"])
        for message in logged
        if failing.unique_id in message.record["message"]
    ]
    assert [level for level, _ in failures] == ["ERROR", "WARNING", "WARNING", "ERROR"]
    assert "attempt 2" in failures[1][1]
    assert "attempt 3" in failures[2][1]


@pytest.fixture
def blocked_tunnel_start(redis_service, monkeypatch):
    """Returns `block(config)`: from then on, starting `config`'s tunnel hangs until the
    test sets the returned `release` event; `started` is set once it hangs.

    A localhost tunnel connects by publishing its URL, so blocking that publish holds the
    start where a slow pyngrok start would be.
    """
    publish_tunnel_url = redis_service.set_tunnel_url
    blocked: dict[str, tuple[asyncio.Event, asyncio.Event]] = {}

    async def publish_blocking(unique_id: str, url: str) -> None:
        if unique_id in blocked:
            started, release = blocked[unique_id]
            started.set()
            await release.wait()
        await publish_tunnel_url(unique_id, url)

    monkeypatch.setattr(redis_service, "set_tunnel_url", publish_blocking)

    def block(config: LocalhostConfigData) -> tuple[asyncio.Event, asyncio.Event]:
        blocked[config.unique_id] = (asyncio.Event(), asyncio.Event())
        return blocked[config.unique_id]

    yield block
    for _, release in blocked.values():
        release.set()


@pytest.mark.parametrize(
    ("new_path", "answers_while_starting", "answers_once_started"),
    [
        ("hook", {"hook": "new-secret"}, {"hook": "new-secret"}),
        # The path is part of the config's id: a renamed webhook is a removal plus a new
        # config, whose path is served once its tunnel has started.
        (
            "moved",
            {"hook": "unregistered", "moved": "unregistered"},
            {"hook": "unregistered", "moved": "new-secret"},
        ),
    ],
    ids=["same-path", "path-changed"],
)
async def test_while_a_restarted_tunnel_starts_its_old_secret_and_old_path_are_not_served(
    tunnel_registry, blocked_tunnel_start, new_path, answers_while_starting, answers_once_started
):
    """A rotation that also restarts the tunnel must not leave the old secret accepted for
    as long as the new tunnel takes to start."""
    hook = LocalhostConfigData(
        name="hook", org_id=1, domain="old.local", auth=_hook_auth("old-secret")
    )
    await tunnel_registry.register_many(WebhookConfigData(localhost_configs=[hook]))
    restarted = hook.model_copy(
        update={"name": new_path, "domain": "new.local", "auth": _hook_auth("new-secret")}
    )
    started, release = blocked_tunnel_start(restarted)
    applying = asyncio.create_task(
        tunnel_registry.register_many(WebhookConfigData(localhost_configs=[restarted]))
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=3)

        assert {
            path: await _path_answer(tunnel_registry, path) for path in answers_while_starting
        } == answers_while_starting
    finally:
        release.set()
        await applying

    assert {
        path: await _path_answer(tunnel_registry, path) for path in answers_once_started
    } == answers_once_started


async def test_an_auth_rotation_applies_while_another_configs_tunnel_is_still_starting(
    tunnel_registry, blocked_tunnel_start
):
    """One organization's slow tunnel restart must not keep another organization's rotated
    secret accepted until the restart finishes."""
    restarting = LocalhostConfigData(
        name="restarting", org_id=1, domain="old.local", auth=_hook_auth("secret")
    )
    rotated = LocalhostConfigData(name="rotated", org_id=2, auth=_hook_auth("old-secret"))
    await tunnel_registry.register_many(
        WebhookConfigData(localhost_configs=[restarting, rotated])
    )
    moved = restarting.model_copy(update={"domain": "new.local"})
    started, release = blocked_tunnel_start(moved)
    applying = asyncio.create_task(
        tunnel_registry.register_many(
            WebhookConfigData(
                # The restart comes first in the set, ahead of the rotation.
                localhost_configs=[
                    moved,
                    rotated.model_copy(update={"auth": _hook_auth("new-secret")}),
                ]
            )
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=3)

        assert await _path_answer(tunnel_registry, "rotated") == "new-secret"
    finally:
        release.set()
        await applying

    assert await _path_answer(tunnel_registry, "rotated") == "new-secret"
    assert await _path_answer(tunnel_registry, "restarting") == "secret"
