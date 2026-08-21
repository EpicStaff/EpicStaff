def test_webhook_endpoint_success(client, mock_redis_service):
    webhook_path = "payment_success"
    payload = {"status": "ok"}

    response = client.post(f"/webhooks/{webhook_path}", json=payload)

    assert response.status_code == 200

    mock_redis_service.publish_webhook.assert_called_once()
    call_args = mock_redis_service.publish_webhook.call_args
    assert call_args[0][0] == webhook_path


def test_webhook_endpoint_query_params(client, mock_redis_service):
    webhook_path = "my-hook"

    query_params = {"a": "1", "b": "2"}

    response = client.post(
        f"/webhooks/{webhook_path}", params=query_params, json={"some": "data"}
    )

    assert response.status_code == 200

    mock_redis_service.publish_webhook.assert_called_once()
