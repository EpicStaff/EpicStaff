from tables.models import OpenAIRealtimeConfig
from tables.services.secrets.policies.base import RowWrite, SecretPolicy


class OpenAIRealtimeConfigSecretPolicy(SecretPolicy):
    reference_fields = ("api_key_secret_id", "transcription_api_key_secret_id")
    approval_model = OpenAIRealtimeConfig
    approval_label = "OpenAI realtime config"

    def destination(self, write: RowWrite) -> dict:
        """The config's own base_url: ConverterService sends both API keys there."""
        return {"base_url": write.value_after_save("base_url")}

    def carries_secret(self, write: RowWrite) -> bool:
        return any(
            write.value_after_save(source, persisted_attribute=f"{source}_id") is not None
            for source in ("api_key_secret", "transcription_api_key_secret")
        )


OPENAI_REALTIME_CONFIG_SECRET_POLICY = OpenAIRealtimeConfigSecretPolicy()
ELEVENLABS_REALTIME_CONFIG_SECRET_POLICY = SecretPolicy(reference_fields=("api_key_secret_id",))
GEMINI_REALTIME_CONFIG_SECRET_POLICY = SecretPolicy(reference_fields=("api_key_secret_id",))
TWILIO_CHANNEL_SECRET_POLICY = SecretPolicy(reference_fields=("auth_token_secret_id",))
