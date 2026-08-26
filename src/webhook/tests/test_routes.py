def test_webhook_endpoint_success(client, mock_redis_service, register_tunnel_path):
    webhook_path = "payment_success"
    payload = {"status": "ok"}
    register_tunnel_path(webhook_path)

    response = client.post(f"/webhooks/{webhook_path}", json=payload)

    assert response.status_code == 200

    mock_redis_service.publish_webhook.assert_called_once()
    call_kwargs = mock_redis_service.publish_webhook.call_args.kwargs
    assert call_kwargs["path"] == webhook_path
    assert call_kwargs["payload"] == payload
    # No auth configured for this path -- fail-open, unrestricted fan-out.
    assert call_kwargs["auth_principal"] is None


def test_webhook_endpoint_query_params(client, mock_redis_service, register_tunnel_path):
    webhook_path = "my-hook"
    register_tunnel_path(webhook_path)

    query_params = {"a": "1", "b": "2"}

    response = client.post(
        f"/webhooks/{webhook_path}", params=query_params, json={"some": "data"}
    )

    assert response.status_code == 200

    mock_redis_service.publish_webhook.assert_called_once()


def test_webhook_endpoint_unregistered_path_returns_404(client, mock_redis_service):
    response = client.post("/webhooks/never-registered", json={"a": 1})

    assert response.status_code == 404
    mock_redis_service.publish_webhook.assert_not_called()
