import json

import httpx
import pytest
from src.shared.models.system_one import SYSTEM_ONE_QUESTIONS_ADAPTER, SystemOneConfigData
from src.shared.system_one.adapter import SYSTEM_ONE_ADAPTERS
from src.shared.system_one.base import SystemOneError
from src.shared.system_one.typesafe_adapter import TYPESAFE_SYSTEM_ONE_URL, TypeSafeAdapter

QUESTIONS = SYSTEM_ONE_QUESTIONS_ADAPTER.validate_python(
    {
        "is_engineering": {"type": "noul", "instructions": "Is this an engineering company?"},
        "department": {
            "type": "choice",
            "instructions": "Department",
            "criteria": {"engineering": "Eng", "sales": "Sales"},
        },
        "size": {"type": "score", "instructions": "Size", "criteria": ["small", "medium", "large"]},
    }
)
STATE = {"company": "Acme Robotics"}
RECORDED = json.loads(
    '{"model":"jev-1.14.0","answers":{"is_engineering":{"type":"noul","noul":0.93},"department":{"type":"choice","choice":"engineering","confidence":1.0,"probabilities":{"engineering":1.0,"sales":0.0}},"size":{"type":"score","score":0.48,"confidence":0.26,"legend":{"0":"small","1":"medium","2":"large"},"probabilities":{"0":0.53,"1":0.45,"2":0.02}}},"usage":{"input_tokens":377,"output_tokens":64}}'
)


def make_config(**overrides) -> SystemOneConfigData:
    return SystemOneConfigData(
        **{
            "id": 1,
            "provider": "typesafe",
            "model_name": "jev-1.14.0",
            "api_key": "ts-key",
            **overrides,
        }
    )


def adapter_answering(response: httpx.Response, seen: list[httpx.Request]) -> TypeSafeAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    return TypeSafeAdapter(transport=httpx.MockTransport(handler))


def adapter_returning(status: int, body: dict, seen: list[httpx.Request]) -> TypeSafeAdapter:
    return adapter_answering(httpx.Response(status, json=body), seen)


async def run(adapter: TypeSafeAdapter, config: SystemOneConfigData | None = None):
    return await adapter.evaluate(config=config or make_config(), state=STATE, questions=QUESTIONS)


def test_the_adapter_is_registered_for_typesafe():
    assert isinstance(SYSTEM_ONE_ADAPTERS["typesafe"], TypeSafeAdapter)


@pytest.mark.asyncio
async def test_one_request_carries_the_pinned_model_state_questions_and_key():
    seen: list[httpx.Request] = []
    await run(adapter_returning(200, RECORDED, seen))
    assert len(seen) == 1
    request = seen[0]
    assert (request.method, str(request.url)) == ("POST", TYPESAFE_SYSTEM_ONE_URL)
    assert request.headers["Authorization"] == "Bearer ts-key"
    assert json.loads(request.content) == {
        "model": "jev-1.14.0",
        "state": STATE,
        "questions": {
            "is_engineering": {"type": "noul", "instructions": "Is this an engineering company?"},
            "department": {
                "type": "choice",
                "instructions": "Department",
                "criteria": {"engineering": "Eng", "sales": "Sales"},
            },
            "size": {
                "type": "score",
                "instructions": "Size",
                "criteria": ["small", "medium", "large"],
            },
        },
    }


@pytest.mark.asyncio
async def test_answers_provider_model_version_and_usage_are_parsed():
    result, usage = await run(adapter_returning(200, RECORDED, []))
    assert result.answers["is_engineering"].noul == 0.93
    assert result.answers["department"].choice == "engineering"
    assert result.answers["size"].score == 0.48
    assert (result.provider, result.model_version) == ("typesafe", "jev-1.14.0")
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (377, 64, 441)
    assert usage.successful_requests == 1


@pytest.mark.asyncio
async def test_cost_is_input_tokens_times_the_pinned_price():
    _, usage = await run(adapter_returning(200, RECORDED, []))
    assert usage.prompt_tokens == 377
    assert usage.total_cost_usd == 0.000015834


@pytest.mark.asyncio
async def test_missing_usage_counts_as_zero():
    body = {key: value for key, value in RECORDED.items() if key != "usage"}
    _, usage = await run(adapter_returning(200, body, []))
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_cost_usd) == (0, 0, 0.0)


@pytest.mark.asyncio
async def test_a_missing_model_falls_back_to_the_pinned_version():
    body = {key: value for key, value in RECORDED.items() if key != "model"}
    result, _ = await run(
        adapter_returning(200, body, []), config=make_config(model_name="jev-1.13.0")
    )
    assert result.model_version == "jev-1.13.0"


@pytest.mark.asyncio
async def test_an_unexpected_model_name_falls_back_to_the_pinned_version():
    result, _ = await run(adapter_returning(200, {**RECORDED, "model": "jev-1.14.0; DROP"}, []))
    assert result.model_version == "jev-1.14.0"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "message"),
    [
        (400, "TypeSafe refused the request (HTTP 400)."),
        (422, "TypeSafe refused the request (HTTP 422)."),
        (401, "TypeSafe rejected the API key."),
        (403, "TypeSafe rejected the API key."),
        (429, "TypeSafe rate limit reached."),
        (402, "TypeSafe returned HTTP 402."),
        (500, "TypeSafe returned HTTP 500."),
    ],
)
async def test_an_error_status_fails_once_with_our_own_message(status, message):
    seen: list[httpx.Request] = []
    with pytest.raises(SystemOneError) as caught:
        await run(adapter_returning(status, {"detail": "secret-looking provider text"}, seen))
    assert str(caught.value) == message
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_a_redirect_is_not_followed():
    seen: list[httpx.Request] = []
    redirect = httpx.Response(302, headers={"Location": "https://evil.example/collect"})
    with pytest.raises(SystemOneError) as caught:
        await run(adapter_answering(redirect, seen))
    assert str(caught.value) == "TypeSafe returned HTTP 302."
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raised", "message"),
    [
        (httpx.ReadTimeout("slow"), "TypeSafe did not answer within 10 seconds."),
        (httpx.ConnectTimeout("slow"), "TypeSafe did not answer within 10 seconds."),
        (httpx.ConnectError("refused for ts-key"), "TypeSafe is unreachable."),
    ],
)
async def test_a_transport_failure_is_a_system_one_error(raised, message):
    def handler(request):
        raise raised

    with pytest.raises(SystemOneError) as caught:
        await run(TypeSafeAdapter(transport=httpx.MockTransport(handler)))
    assert str(caught.value) == message
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        pytest.param(httpx.Response(200, text="<html>not json</html>"), id="non-json"),
        pytest.param(httpx.Response(200, json=[1, 2]), id="json-not-an-object"),
        pytest.param(httpx.Response(200, json={"model": "jev-1.14.0"}), id="no-answers"),
        pytest.param(
            httpx.Response(
                200,
                json={
                    **RECORDED,
                    "answers": {**RECORDED["answers"], "is_engineering": {"type": "noul"}},
                },
            ),
            id="malformed-answer",
        ),
        pytest.param(
            httpx.Response(200, json={**RECORDED, "usage": {"input_tokens": "many"}}),
            id="malformed-usage",
        ),
    ],
)
async def test_a_malformed_body_is_a_system_one_error(response):
    with pytest.raises(SystemOneError) as caught:
        await run(adapter_answering(response, []))
    assert str(caught.value) == "TypeSafe returned a malformed answer."
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", [None, "", "  \n", "ts\nkey", "ts-k\u00e9y"])
async def test_an_unusable_key_sends_nothing_and_leaves_no_trace(api_key):
    seen: list[httpx.Request] = []
    with pytest.raises(SystemOneError) as caught:
        await run(adapter_returning(200, RECORDED, seen), config=make_config(api_key=api_key))
    assert str(caught.value) == "The config has no API key."
    assert seen == []
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.asyncio
async def test_whitespace_around_the_key_is_stripped():
    seen: list[httpx.Request] = []
    await run(adapter_returning(200, RECORDED, seen), config=make_config(api_key=" ts-key\n"))
    assert seen[0].headers["Authorization"] == "Bearer ts-key"


@pytest.mark.asyncio
@pytest.mark.parametrize("model_name", [None, "", "jev-9.9.9"])
async def test_a_config_without_a_supported_version_sends_nothing(model_name):
    seen: list[httpx.Request] = []
    with pytest.raises(SystemOneError) as caught:
        await run(adapter_returning(200, RECORDED, seen), config=make_config(model_name=model_name))
    assert str(caught.value) == "The config has no supported Jev version."
    assert seen == []


@pytest.mark.asyncio
async def test_error_messages_never_contain_the_body_or_the_key():
    secret_body = httpx.Response(422, text='{"detail": "secret-detail ts-key"}')
    with pytest.raises(SystemOneError) as caught:
        await run(adapter_answering(secret_body, []))
    assert "secret-detail" not in str(caught.value)
    assert "ts-key" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "usage",
    [
        pytest.param(None, id="usage-null"),
        pytest.param({"input_tokens": None, "output_tokens": None}, id="tokens-null"),
    ],
)
async def test_null_usage_counts_as_zero_and_keeps_the_answer(usage):
    result, token_usage = await run(adapter_returning(200, {**RECORDED, "usage": usage}, []))
    assert result.answers["department"].choice == "engineering"
    assert (
        token_usage.prompt_tokens,
        token_usage.completion_tokens,
        token_usage.total_cost_usd,
    ) == (
        0,
        0,
        0.0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [None, 7, ["jev-1.14.0"], {"v": 1}])
async def test_a_non_string_model_falls_back_to_the_pinned_version(model):
    result, _ = await run(adapter_returning(200, {**RECORDED, "model": model}, []))
    assert result.model_version == "jev-1.14.0"
