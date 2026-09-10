import uuid
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from tables.models.realtime_models import (
    RealtimeAgentChat,
    RealtimeAgentDefinition,
)

from utils.logger import logger
from utils.singleton_meta import SingletonMeta
from tables.services.converter_service import ConverterService
from tables.services.redis_service import RedisService

# `config` (from `InitRealtimeSerializer.config`, a bare `DictField`) is
# client-supplied and, until this whitelist, was `setattr`'d onto the
# already pydantic-validated `RealtimeAgentChatData` for ANY key matching a
# field name via `hasattr` -- with zero type/value checking, bypassing
# pydantic entirely.
#
# Two legitimate override use cases exist today:
#   - `input_audio_format` / `output_audio_format`: the built-in Twilio
#     bridge's `_voice_stream_handler` (src/realtime/api/main.py) always
#     sends both, to switch the session to g711_ulaw.
#   - `rt_api_key_secret_id`: a browser/JWT caller overriding which of their
#     own org's Secret rows supplies the realtime API key. This one is NOT
#     a plain value -- SecretResolver re-resolves it org-scoped at publish
#     time (`secret_resolver.resolve_payload`, keyed off the requester's
#     own `org_id`), which is what actually blocks a foreign-org secret id
#     from decrypting (see test_init_realtime_cross_org_secret.py /
#     test_init_realtime_agent_definition_secret.py) -- that protection is
#     independent of, and unaffected by, this whitelist.
# Restricting to this fixed set closes the "any field, unchecked" gap
# without changing any of today's real callers' behavior; anything else is
# dropped (and logged) rather than silently applied.
_ALLOWED_CONFIG_OVERRIDE_KEYS = frozenset(
    {"input_audio_format", "output_audio_format", "rt_api_key_secret_id"}
)


def _apply_config_overrides(rt_agent_chat_data, config: dict) -> None:
    """Apply only whitelisted `config` overrides onto `rt_agent_chat_data`.

    Any key outside `_ALLOWED_CONFIG_OVERRIDE_KEYS` is ignored rather than
    `setattr`'d -- see the whitelist comment above for why.
    """
    for key, value in config.items():
        if key not in _ALLOWED_CONFIG_OVERRIDE_KEYS:
            logger.warning(
                "init_realtime: ignoring non-whitelisted config override key "
                "'{}' for connection_key={} -- if this is a legitimate new "
                "override, add it to _ALLOWED_CONFIG_OVERRIDE_KEYS.",
                key,
                rt_agent_chat_data.connection_key,
            )
            continue
        if hasattr(rt_agent_chat_data, key):
            setattr(rt_agent_chat_data, key, value)


class RealtimeService(metaclass=SingletonMeta):
    def __init__(
        self,
        redis_service: RedisService,
        converter_service: ConverterService,
    ) -> None:
        self.redis_service = redis_service
        self.converter_service = converter_service

    def get_rt_agent_definition(
        self, agent_definition_id: int
    ) -> RealtimeAgentDefinition:
        rt_agent_definition = get_object_or_404(
            RealtimeAgentDefinition.objects.select_related(
                "openai_config",
                "elevenlabs_config",
                "gemini_config",
            ),
            pk=agent_definition_id,
        )
        self.validate_rt_agent_definition(rt_agent_definition)
        return rt_agent_definition

    def validate_rt_agent_definition(
        self, rt_agent_definition: RealtimeAgentDefinition
    ):
        if rt_agent_definition.active_provider_config is None:
            raise ValidationError(
                f"RealtimeAgentDefinition ID {rt_agent_definition.pk} has no "
                "provider config set. Assign an openai_config, "
                "elevenlabs_config, or gemini_config."
            )

    def generate_connection_key(self):
        return str(uuid.uuid4())

    def create_rt_agent_definition_chat(
        self, rt_agent_definition: RealtimeAgentDefinition
    ) -> RealtimeAgentChat:
        connection_key = self.generate_connection_key()

        # RealtimeAgentDefinition (unlike RealtimeAgent) still carries its own
        # language/voice_recognition_prompt fields — snapshot those directly,
        # only falling back to the config's own value when the definition
        # doesn't set one.
        chat_kwargs = dict(
            rt_agent_definition=rt_agent_definition,
            wake_word=rt_agent_definition.wake_word,
            stop_prompt=rt_agent_definition.stop_prompt,
            voice=rt_agent_definition.voice,
            language=rt_agent_definition.language,
            voice_recognition_prompt=rt_agent_definition.voice_recognition_prompt,
            connection_key=connection_key,
        )

        if rt_agent_definition.openai_config:
            chat_kwargs.update(
                openai_config=rt_agent_definition.openai_config,
                input_audio_format="pcm16",
                output_audio_format="pcm16",
            )
        elif rt_agent_definition.elevenlabs_config:
            cfg = rt_agent_definition.elevenlabs_config
            chat_kwargs.update(
                elevenlabs_config=cfg,
                language=rt_agent_definition.language or cfg.language,
            )
        elif rt_agent_definition.gemini_config:
            chat_kwargs.update(gemini_config=rt_agent_definition.gemini_config)

        return RealtimeAgentChat.objects.create(**chat_kwargs)

    def init_realtime_agent_definition(
        self,
        *,
        agent_definition_id: int,
        config: dict,
        org_id: int,
        user_id: int | None = None,
    ) -> str:
        rt_agent_definition = self.get_rt_agent_definition(
            agent_definition_id=agent_definition_id
        )
        rt_agent_chat = self.create_rt_agent_definition_chat(rt_agent_definition)

        rt_agent_chat_data = (
            self.converter_service.convert_rt_agent_definition_chat_to_pydantic(
                rt_agent_chat=rt_agent_chat, user_id=user_id
            )
        )
        # Override with provided config (whitelisted keys only, see
        # _apply_config_overrides)
        _apply_config_overrides(rt_agent_chat_data, config)

        self.redis_service.publish_realtime_agent_chat(
            rt_agent_chat_data=rt_agent_chat_data,
            org_id=org_id,
        )
        return rt_agent_chat_data.connection_key
