TYPESAFE_PROVIDER = "typesafe"
LLM_PROVIDER = "llm"
# Pinned Jev versions, newest first. A new Jev version is a code change.
JEV_MODEL_VERSIONS: tuple[str, ...] = ("jev-1.14.0", "jev-1.13.0")
# Input price per token. Source: https://docs.typesafe.ai/models.md (checked 2026-10-30); output tokens are free.
JEV_INPUT_PRICE_USD_PER_TOKEN: dict[str, float] = {"jev-1.14.0": 0.042e-6, "jev-1.13.0": 0.042e-6}

OPENAI_PROVIDER = "openai"
OPENAI_DECISIONS_MODELS: tuple[str, ...] = ("gpt-6-luna",)
# Input price per token. Source: https://developers.openai.com/api/docs/guides/decisions (checked 2026-11-06); output tokens are free.
OPENAI_INPUT_PRICE_USD_PER_TOKEN: dict[str, float] = {"gpt-6-luna": 0.10e-6}
SYSTEM_ONE_MODELS_BY_PROVIDER: dict[str, tuple[str, ...]] = {
    TYPESAFE_PROVIDER: JEV_MODEL_VERSIONS,
    OPENAI_PROVIDER: OPENAI_DECISIONS_MODELS,
}
