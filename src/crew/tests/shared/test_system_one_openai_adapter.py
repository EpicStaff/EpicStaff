import json

import httpx
import pytest
from src.shared.models.system_one import SYSTEM_ONE_QUESTIONS_ADAPTER, SystemOneConfigData
from src.shared.system_one.adapter import SYSTEM_ONE_ADAPTERS
from src.shared.system_one.base import SystemOneError
from src.shared.system_one.openai_adapter import OPENAI_DECISIONS_URL, OpenAIDecisionsAdapter

QUESTIONS = SYSTEM_ONE_QUESTIONS_ADAPTER.validate_python(
    {
        "is_engineering": {"type": "noul", "instructions": "Is this an engineering company?"},
        "department": {
            "type": "choice",
            "instructions": "Department",
            "criteria": {"engineering": "Eng", "sales": ""},
        },
        "size": {"type": "score", "instructions": "Size", "criteria": ["small", "medium", "large"]},
    }
)
STATE = {"company": "Acme Robotics"}
RECORDED = json.loads(
    '{"model":"gpt-6-luna","answers":[{"type":"predicate","name":"is_engineering","probability":0.95},{"type":"choice","name":"department","choice":"engineering","probabilities":[{"value":"engineering","probability":0.97},{"value":"sales","probability":0.03}],"confidence":0.94},{"type":"score","name":"size","score":1.0,"probabilities":[{"value":0,"label":"small","probability":0.0},{"value":1,"label":"medium","probability":1.0},{"value":2,"label":"large","probability":0.0}],"confidence":1.0}],"usage":{"input_tokens":420,"input_tokens_details":{"cached_tokens":0,"cache_write_tokens":0},"output_tokens":0,"output_tokens_details":{"reasoning_tokens":0},"total_tokens":420}}'
)
SPREAD_SCORE = json.loads(
    '{"model":"gpt-6-luna","answers":[{"type":"score","name":"size","score":0.72,"probabilities":[{"value":0,"label":"small","probability":0.29},{"value":1,"label":"medium","probability":0.7},{"value":2,"label":"large","probability":0.01}],"confidence":0.55}],"usage":{"input_tokens":148,"input_tokens_details":{"cached_tokens":0,"cache_write_tokens":0},"output_tokens":0,"output_tokens_details":{"reasoning_tokens":0},"total_tokens":148}}'
)
ALL_REFUSED = {
    **RECORDED,
    "answers": [{"type": "refusal", "name": name} for name in QUESTIONS],
}
ONE_REFUSED = {
    **RECORDED,
    "answers": [
        {"type": "refusal", "name": "department"} if answer["name"] == "department" else answer
        for answer in RECORDED["answers"]
    ],
}
INVALID_KEY_BODY = {
    "error": {
        "message": "Incorrect API key provided: sk-test. You can find your API key at ...",
        "type": "invalid_request_error",
        "param": None,
        "code": "invalid_api_key",
    }
}


def make_config(**overrides) -> SystemOneConfigData:
    return SystemOneConfigData(
        **{
            "id": 1,
            "provider": "openai",
            "model_name": "gpt-6-luna",
            "api_key": "sk-test",
            **overrides,
        }
    )


def adapter_answering(
    response: httpx.Response, seen: list[httpx.Request]
) -> OpenAIDecisionsAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    return OpenAIDecisionsAdapter(transport=httpx.MockTransport(handler))


def adapter_returning(
    status: int, body: dict, seen: list[httpx.Request]
) -> OpenAIDecisionsAdapter:
    return adapter_answering(httpx.Response(status, json=body), seen)


async def run(adapter: OpenAIDecisionsAdapter, config: SystemOneConfigData | None = None):
    return await adapter.evaluate(config=config or make_config(), state=STATE, questions=QUESTIONS)


def test_the_adapter_is_registered_for_openai():
    assert isinstance(SYSTEM_ONE_ADAPTERS["openai"], OpenAIDecisionsAdapter)


@pytest.mark.asyncio
async def test_one_request_carries_the_model_state_questions_and_key():
    seen: list[httpx.Request] = []
    await run(adapter_returning(200, RECORDED, seen))
    assert len(seen) == 1
    request = seen[0]
    assert (request.method, str(request.url)) == ("POST", OPENAI_DECISIONS_URL)
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert json.loads(request.content) == {
        "model": "gpt-6-luna",
        "input": [{"role": "user", "content": [{"type": "input_json", "data": STATE}]}],
        "questions": [
            {
                "type": "predicate",
                "name": "is_engineering",
                "instructions": "Is this an engineering company?",
            },
            {
                "type": "choice",
                "name": "department",
                "instructions": "Department",
                "choices": [{"value": "engineering", "description": "Eng"}, {"value": "sales"}],
            },
            {
                "type": "score",
                "name": "size",
                "instructions": "Size",
                "levels": [{"label": "small"}, {"label": "medium"}, {"label": "large"}],
            },
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("criteria", "instructions"),
    [
        ({"true": "a", "false": "b"}, "Q\nTrue when: a\nFalse when: b"),
        ({"true": "a"}, "Q\nTrue when: a"),
        ({"false": "b"}, "Q\nFalse when: b"),
    ],
)
async def test_noul_criteria_are_appended_to_the_instructions(criteria, instructions):
    seen: list[httpx.Request] = []
    questions = SYSTEM_ONE_QUESTIONS_ADAPTER.validate_python(
        {"is_engineering": {"type": "noul", "instructions": "Q", "criteria": criteria}}
    )
    adapter = adapter_returning(200, {**RECORDED, "answers": RECORDED["answers"][:1]}, seen)
    await adapter.evaluate(config=make_config(), state=STATE, questions=questions)
    assert json.loads(seen[0].content)["questions"] == [
        {"type": "predicate", "name": "is_engineering", "instructions": instructions}
    ]


@pytest.mark.asyncio
async def test_answers_are_converted_to_the_shared_shape():
    result, _ = await run(adapter_returning(200, RECORDED, []))
    assert result.answers["is_engineering"].noul == 0.95
    department = result.answers["department"]
    assert department.choice == "engineering"
    assert department.confidence == 0.94
    assert department.probabilities == {"engineering": 0.97, "sales": 0.03}
    size = result.answers["size"]
    assert size.score == 1.0
    assert size.confidence == 1.0
    assert size.probabilities == {"0": 0.0, "1": 1.0, "2": 0.0}
    assert (result.provider, result.model_version) == ("openai", "gpt-6-luna")


@pytest.mark.asyncio
async def test_score_is_passed_through_as_the_expected_value():
    result, _ = await run(adapter_returning(200, SPREAD_SCORE, []))
    assert result.answers["size"].score == 0.72
    assert result.answers["size"].probabilities == {"0": 0.29, "1": 0.7, "2": 0.01}


@pytest.mark.asyncio
async def test_answers_are_matched_by_name_not_position():
    forward, _ = await run(adapter_returning(200, RECORDED, []))
    reversed_body = {**RECORDED, "answers": RECORDED["answers"][::-1]}
    backward, _ = await run(adapter_returning(200, reversed_body, []))
    assert backward == forward


@pytest.mark.asyncio
async def test_cost_is_input_tokens_times_the_price():
    _, usage = await run(adapter_returning(200, RECORDED, []))
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (420, 0, 420)
    assert usage.successful_requests == 1
    assert usage.total_cost_usd == round(420 * 0.10e-6, 10)


@pytest.mark.asyncio
async def test_an_unexpected_model_name_falls_back_to_the_pinned_model():
    result, _ = await run(adapter_returning(200, {**RECORDED, "model": "gpt-7"}, []))
    assert result.model_version == "gpt-6-luna"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [ALL_REFUSED, ONE_REFUSED], ids=["all-refused", "one-refused"])
async def test_a_refusal_fails_the_whole_entry(body):
    with pytest.raises(SystemOneError) as caught:
        await run(adapter_returning(200, body, []))
    assert str(caught.value) == "OpenAI declined to answer."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "message"),
    [
        (400, "OpenAI refused the request (HTTP 400)."),
        (422, "OpenAI refused the request (HTTP 422)."),
        (401, "OpenAI rejected the API key."),
        (403, "OpenAI rejected the API key."),
        (429, "OpenAI rate limit reached."),
        (404, "OpenAI returned HTTP 404."),
        (500, "OpenAI returned HTTP 500."),
    ],
)
async def test_an_error_status_fails_once_with_our_own_message(status, message):
    seen: list[httpx.Request] = []
    with pytest.raises(SystemOneError) as caught:
        await run(adapter_returning(status, {"error": {"message": "secret-looking text"}}, seen))
    assert str(caught.value) == message
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_a_redirect_is_not_followed():
    seen: list[httpx.Request] = []
    redirect = httpx.Response(302, headers={"Location": "https://evil.example/collect"})
    with pytest.raises(SystemOneError) as caught:
        await run(adapter_answering(redirect, seen))
    assert str(caught.value) == "OpenAI returned HTTP 302."
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raised", "message"),
    [
        (httpx.ReadTimeout("slow"), "OpenAI did not answer within 10 seconds."),
        (httpx.ConnectTimeout("slow"), "OpenAI did not answer within 10 seconds."),
        (httpx.ConnectError("refused for sk-test"), "OpenAI is unreachable."),
    ],
)
async def test_a_transport_failure_is_a_system_one_error(raised, message):
    def handler(request):
        raise raised

    with pytest.raises(SystemOneError) as caught:
        await run(OpenAIDecisionsAdapter(transport=httpx.MockTransport(handler)))
    assert str(caught.value) == message
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def with_answer(position: int, **changes) -> dict:
    answers = [dict(answer) for answer in RECORDED["answers"]]
    answers[position] = {**answers[position], **changes}
    return {**RECORDED, "answers": answers}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        pytest.param(httpx.Response(200, text="<html>not json</html>"), id="non-json"),
        pytest.param(httpx.Response(200, json=[1, 2]), id="json-not-an-object"),
        pytest.param(httpx.Response(200, json={"model": "gpt-6-luna"}), id="no-answers"),
        pytest.param(
            httpx.Response(200, json=with_answer(0, type="mystery")), id="unknown-answer-type"
        ),
        pytest.param(
            httpx.Response(200, json=with_answer(0, probability=1.5)), id="probability-above-one"
        ),
        pytest.param(
            httpx.Response(200, json=with_answer(1, choice={"a": 1})), id="choice-value-object"
        ),
        pytest.param(httpx.Response(200, json=with_answer(1, choice=True)), id="choice-value-bool"),
        pytest.param(
            httpx.Response(
                200,
                json=with_answer(2, probabilities=[{"value": "0", "probability": 1.0}]),
            ),
            id="score-value-string",
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
    assert str(caught.value) == "OpenAI returned a malformed answer."
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", [None, "", "  \n", "sk\ntest", "sk-tést"])
async def test_an_unusable_key_sends_nothing_and_leaves_no_trace(api_key):
    seen: list[httpx.Request] = []
    with pytest.raises(SystemOneError) as caught:
        await run(adapter_returning(200, RECORDED, seen), config=make_config(api_key=api_key))
    assert str(caught.value) == "The config has no API key."
    assert seen == []
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize("model_name", [None, "", "jev-1.14.0"])
async def test_a_config_without_a_supported_model_sends_nothing(model_name):
    seen: list[httpx.Request] = []
    with pytest.raises(SystemOneError) as caught:
        await run(adapter_returning(200, RECORDED, seen), config=make_config(model_name=model_name))
    assert str(caught.value) == "The config has no supported OpenAI model."
    assert seen == []


@pytest.mark.asyncio
async def test_error_messages_never_contain_the_body_or_the_key():
    with pytest.raises(SystemOneError) as caught:
        await run(adapter_returning(401, INVALID_KEY_BODY, []))
    assert "sk-test" not in str(caught.value)
    assert "Incorrect API key" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [None, 7, ["gpt-6-luna"], {"v": 1}])
async def test_a_non_string_model_falls_back_to_the_pinned_model(model):
    result, _ = await run(adapter_returning(200, {**RECORDED, "model": model}, []))
    assert result.model_version == "gpt-6-luna"
