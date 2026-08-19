import uuid
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from tables.models.realtime_models import (
    RealtimeAgent,
    RealtimeAgentChat,
    RealtimeAgentDefinition,
)

from utils.singleton_meta import SingletonMeta
from tables.services.converter_service import ConverterService
from tables.services.redis_service import RedisService


class RealtimeService(metaclass=SingletonMeta):
    def __init__(
        self,
        redis_service: RedisService,
        converter_service: ConverterService,
    ) -> None:
        self.redis_service = redis_service
        self.converter_service = converter_service

    def get_rt_agent(self, agent_id: int) -> RealtimeAgent:
        rt_agent = get_object_or_404(
            RealtimeAgent.objects.select_related(
                "openai_config",
                "elevenlabs_config",
                "gemini_config",
            ),
            pk=agent_id,
        )
        self.validate_rt_agent(rt_agent)
        return rt_agent

    def validate_rt_agent(self, rt_agent: RealtimeAgent):
        if rt_agent.active_provider_config is None:
            raise ValidationError(
                f"RealtimeAgent ID {rt_agent.pk} has no provider config set. "
                "Assign an openai_config, elevenlabs_config, or gemini_config."
            )

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

    def create_rt_agent_chat(self, rt_agent: RealtimeAgent) -> RealtimeAgentChat:
        connection_key = self.generate_connection_key()

        chat_kwargs = dict(
            rt_agent=rt_agent,
            wake_word=rt_agent.wake_word,
            stop_prompt=rt_agent.stop_prompt,
            voice=rt_agent.voice,
            connection_key=connection_key,
        )

        if rt_agent.openai_config:
            cfg = rt_agent.openai_config
            chat_kwargs.update(
                openai_config=cfg,
                voice_recognition_prompt=cfg.voice_recognition_prompt,
                input_audio_format="pcm16",
                output_audio_format="pcm16",
            )
        elif rt_agent.elevenlabs_config:
            cfg = rt_agent.elevenlabs_config
            chat_kwargs.update(
                elevenlabs_config=cfg,
                language=cfg.language,
            )
        elif rt_agent.gemini_config:
            cfg = rt_agent.gemini_config
            chat_kwargs.update(
                gemini_config=cfg,
                voice_recognition_prompt=cfg.voice_recognition_prompt,
            )

        return RealtimeAgentChat.objects.create(**chat_kwargs)

    def init_realtime(self, agent_id: int, config: dict) -> str:
        rt_agent = self.get_rt_agent(agent_id=agent_id)
        rt_agent_chat = self.create_rt_agent_chat(rt_agent)

        rt_agent_chat_data = self.converter_service.convert_rt_agent_chat_to_pydantic(
            rt_agent_chat=rt_agent_chat
        )
        # Override with provided config
        for key, value in config.items():
            if hasattr(rt_agent_chat_data, key):
                setattr(rt_agent_chat_data, key, value)

        self.redis_service.publish_realtime_agent_chat(
            rt_agent_chat_data=rt_agent_chat_data
        )
        return rt_agent_chat_data.connection_key

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
        self, agent_definition_id: int, config: dict
    ) -> str:
        rt_agent_definition = self.get_rt_agent_definition(
            agent_definition_id=agent_definition_id
        )
        rt_agent_chat = self.create_rt_agent_definition_chat(rt_agent_definition)

        rt_agent_chat_data = (
            self.converter_service.convert_rt_agent_definition_chat_to_pydantic(
                rt_agent_chat=rt_agent_chat
            )
        )
        # Override with provided config
        for key, value in config.items():
            if hasattr(rt_agent_chat_data, key):
                setattr(rt_agent_chat_data, key, value)

        self.redis_service.publish_realtime_agent_chat(
            rt_agent_chat_data=rt_agent_chat_data
        )
        return rt_agent_chat_data.connection_key
