from litestar.status_codes import HTTP_200_OK


async def test_health(client):
    response = await client.get("/chat/health")
    assert response.status_code == HTTP_200_OK
    assert response.json() == {"status": "ok"}


async def test_http_error_is_not_logged_as_error(client):
    from loguru import logger

    records: list[str] = []
    sink_id = logger.add(records.append, level="ERROR")
    try:
        response = await client.post("/chat/health")
    finally:
        logger.remove(sink_id)
    assert response.status_code == 405 and response.json()["code"] == "http_error"
    assert records == []
