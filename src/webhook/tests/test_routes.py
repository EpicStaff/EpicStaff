def test_webhook_endpoint_no_auth_configured_is_rejected(
    client, mock_redis_service, register_tunnel_path
):
    """A path with no `WebhookTriggerAuth` row at all (`config.auth is None`)
    must fail closed -- there is no legitimate unauthenticated dispatch case
    left in this design (see EST-3939)."""
    webhook_path = "payment_success"
    payload = {"status": "ok"}
    register_tunnel_path(webhook_path)

    response = client.post(f"/webhooks/{webhook_path}", json=payload)

    assert response.status_code == 401
    mock_redis_service.publish_webhook.assert_not_called()


def test_webhook_endpoint_query_params(client, mock_redis_service, register_tunnel_path):
    webhook_path = "my-hook"
    register_tunnel_path(webhook_path, auth=_auth("webhook", "correct-secret"))

    query_params = {"a": "1", "b": "2"}

    response = client.post(
        f"/webhooks/{webhook_path}",
        params=query_params,
        json={"some": "data"},
        headers={"EPICSTAFF_API_KEY": "correct-secret"},
    )

    assert response.status_code == 200

    mock_redis_service.publish_webhook.assert_called_once()


def test_webhook_endpoint_unregistered_path_returns_404(client, mock_redis_service):
    response = client.post("/webhooks/never-registered", json={"a": 1})

    assert response.status_code == 404
    mock_redis_service.publish_webhook.assert_not_called()


def _auth(kind: str, secret: str):
    from src.shared.models import WebhookTriggerAuthData

    header_name = {
        "webhook": "EPICSTAFF_API_KEY",
        "telegram": "X-Telegram-Bot-Api-Secret-Token",
    }[kind]
    return WebhookTriggerAuthData(kind=kind, header_name=header_name, secret=secret)


def test_webhook_endpoint_rejects_missing_header_when_auth_configured(
    client, mock_redis_service, register_tunnel_path
):
    webhook_path = "authed-hook"
    register_tunnel_path(webhook_path, auth=_auth("webhook", "correct-secret"))

    response = client.post(f"/webhooks/{webhook_path}", json={"a": 1})

    assert response.status_code == 401
    mock_redis_service.publish_webhook.assert_not_called()


def test_webhook_endpoint_rejects_wrong_secret(
    client, mock_redis_service, register_tunnel_path
):
    webhook_path = "authed-hook-2"
    register_tunnel_path(webhook_path, auth=_auth("webhook", "correct-secret"))

    response = client.post(
        f"/webhooks/{webhook_path}",
        json={"a": 1},
        headers={"EPICSTAFF_API_KEY": "wrong-secret"},
    )

    assert response.status_code == 401
    mock_redis_service.publish_webhook.assert_not_called()


def test_webhook_endpoint_accepts_correct_epicstaff_api_key(
    client, mock_redis_service, register_tunnel_path
):
    webhook_path = "authed-hook-3"
    register_tunnel_path(webhook_path, auth=_auth("webhook", "correct-secret"))

    response = client.post(
        f"/webhooks/{webhook_path}",
        json={"a": 1},
        headers={"EPICSTAFF_API_KEY": "correct-secret"},
    )

    assert response.status_code == 200
    mock_redis_service.publish_webhook.assert_called_once()


def test_webhook_endpoint_accepts_correct_telegram_secret_token(
    client, mock_redis_service, register_tunnel_path
):
    webhook_path = "telegram-trigger/authed-bot"
    register_tunnel_path(webhook_path, auth=_auth("telegram", "tg-secret"))

    response = client.post(
        f"/webhooks/{webhook_path}",
        json={"a": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret"},
    )

    assert response.status_code == 200
    mock_redis_service.publish_webhook.assert_called_once()


