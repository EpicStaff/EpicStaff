import uuid
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from tables.models.realtime_models import RealtimeAgentChat, RealtimeAgent

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
        rt_agent = get_object_or_404(RealtimeAgent, pk=agent_id)
        self.validate_rt_agent(rt_agent)
        return rt_agent

    def validate_rt_agent(self, rt_agent: RealtimeAgent):
        missing_fields = []

        if rt_agent.realtime_config is None:
            missing_fields.append("realtime_config")

        # ElevenLabs handles STT internally — transcription config not required
        provider = (
            rt_agent.realtime_config.realtime_model.provider.name
            if rt_agent.realtime_config
            else None
        )
        if (
            provider not in ("elevenlabs", "gemini")
            and rt_agent.realtime_transcription_config is None
        ):
            missing_fields.append("realtime_transcription_config")

        if missing_fields:
            raise ValidationError(
                f"RealtimeAgent ID {rt_agent.pk} is missing required fields: {', '.join(missing_fields)}"
            )

    def generate_connection_key(self):
        return str(uuid.uuid4())

    def create_rt_agent_chat(self, rt_agent: RealtimeAgent) -> RealtimeAgentChat:
        connection_key = self.generate_connection_key()
        return RealtimeAgentChat.objects.create(
            rt_agent=rt_agent,
            wake_word=rt_agent.wake_word,
            stop_prompt=rt_agent.stop_prompt,
            language=rt_agent.language,
            voice_recognition_prompt=rt_agent.voice_recognition_prompt,
            voice=rt_agent.voice,
            realtime_config=rt_agent.realtime_config,
            realtime_transcription_config=rt_agent.realtime_transcription_config,
            connection_key=connection_key,
        )

    def init_realtime(self, *, agent_id: int, config: dict, org_id: int) -> str:
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
            rt_agent_chat_data=rt_agent_chat_data,
            org_id=org_id,
        )
        return rt_agent_chat_data.connection_key
