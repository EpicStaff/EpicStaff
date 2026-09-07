import asyncio
import base64
import io
import json
import struct
import time
from typing import Optional

import httpx
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

try:
    from websockets.exceptions import ConnectionClosedOK as _WsClosedOK
except ImportError:
    _WsClosedOK = None

from src.shared.models import RealtimeAgentChatData

from domain.ports.i_realtime_agent_client import IRealtimeAgentClient
from infrastructure.providers.factory import RealtimeAgentClientFactory
from application.tool_manager_service import ToolManagerService

MIN_CHUNK_SIZE = 2000
DEFAULT_MAX_CALL_DURATION_SECONDS = 1800  # 30 min metering ceiling


def _build_ulaw_wav(raw_ulaw: bytes, sample_rate: int = 8000) -> bytes:
    """Wrap raw µ-law bytes in a WAVE container (no re-encoding)."""
    num_channels = 1
    bits_per_sample = 8
    audio_format = 7  # WAVE_FORMAT_MULAW
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(raw_ulaw)
    chunk_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        chunk_size,
        b"WAVE",
        b"fmt ",
        16,  # PCM chunk size (16 for standard WAV)
        audio_format,
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + raw_ulaw


class VoiceCallService:
    """
    Use case: bridges a Twilio MediaStream WebSocket to a realtime AI provider.
    Zero provider-specific code — all audio format differences are handled inside
    the provider adapters (send_audio for input, server event handler for output).
    """

    def __init__(
        self,
        twilio_ws: WebSocket,
        realtime_agent_chat_data: RealtimeAgentChatData,
        instructions: str,
        tool_manager_service: ToolManagerService,
        connections: dict,
        factory: RealtimeAgentClientFactory,
        django_api_base_url: str,
        django_api_key: str = "",
        initial_message: Optional[dict] = None,
        max_call_duration_seconds: int = DEFAULT_MAX_CALL_DURATION_SECONDS,
    ):
        self.twilio_ws = twilio_ws
        self.realtime_agent_chat_data = realtime_agent_chat_data
        self.instructions = instructions
        self.tool_manager_service = tool_manager_service
        self.connections = connections
        self.factory = factory
        self.django_api_base_url = django_api_base_url
        self.django_api_key = django_api_key
        self.initial_message = initial_message
        self.max_call_duration_seconds = max_call_duration_seconds

        self.stream_sid: Optional[str] = None
        self.audio_accumulator = bytearray()

        self._start_time: float = time.monotonic()
        self._end_reason: str = "completed"
        self._inbound_chunks: list[bytes] = []   # user audio (µ-law 8kHz from Twilio)
        self._outbound_chunks: list[bytes] = []  # agent audio (µ-law 8kHz to Twilio)

    async def execute(self):
        self.tool_manager_service.register_tools_from_rt_agent_chat_data(
            realtime_agent_chat_data=self.realtime_agent_chat_data,
            chat_mode_controller=None,
        )
        rt_tools = await self.tool_manager_service.get_realtime_tool_models(
            connection_key=self.realtime_agent_chat_data.connection_key
        )

        rt_agent_client: IRealtimeAgentClient = self.factory.create(
            config=self.realtime_agent_chat_data,
            rt_tools=rt_tools,
            instructions=self.instructions,
            tool_manager_service=self.tool_manager_service,
            on_server_event=self._handle_provider_event,
            is_twilio=True,
        )

        await rt_agent_client.connect()
        logger.success(
            f"Voice stream connected to provider: {self.realtime_agent_chat_data.rt_provider}"
        )

        self._start_time = time.monotonic()
        message_task = asyncio.create_task(rt_agent_client.handle_messages())
        try:
            if self.initial_message:
                await self._handle_twilio_message(self.initial_message, rt_agent_client)
            async for raw in self.twilio_ws.iter_text():
                # Defense-in-depth metering ceiling: a leaked/stolen stream
                # token (or a runaway call) can't run up provider costs
                # forever — cap wall-clock session duration server-side.
                if time.monotonic() - self._start_time > self.max_call_duration_seconds:
                    logger.warning(
                        f"Voice call exceeded max duration "
                        f"({self.max_call_duration_seconds}s) — ending session"
                    )
                    self._end_reason = "max_duration_exceeded"
                    break
                await self._handle_twilio_message(json.loads(raw), rt_agent_client)
        except WebSocketDisconnect as e:
            if e.code == 1000:
                logger.info("Twilio WebSocket closed normally (call ended)")
            else:
                logger.warning(f"Twilio WebSocket disconnected: code={e.code}")
                self._end_reason = "cancelled"
        except Exception as e:
            if _WsClosedOK and isinstance(e, _WsClosedOK):
                logger.info("Twilio WebSocket closed normally (call ended)")
            else:
                logger.error(f"Twilio WebSocket Error: {e}")
                self._end_reason = "error"
        finally:
            message_task.cancel()
            try:
                await message_task
            except asyncio.CancelledError:
                pass
            await rt_agent_client.close()

            if self._end_reason == "max_duration_exceeded":
                # We broke out of the loop ourselves (Twilio didn't hang up) —
                # actively close so the call actually ends instead of hanging
                # open with nobody reading Twilio's media frames.
                try:
                    await self.twilio_ws.close()
                except Exception as e:
                    logger.debug(f"Error closing Twilio WebSocket after max duration: {e}")

            duration = time.monotonic() - self._start_time
            asyncio.create_task(self._save_recordings(duration))

    async def _handle_twilio_message(
        self, data: dict, client: IRealtimeAgentClient
    ) -> None:
        event = data.get("event")
        if event == "start":
            self.stream_sid = data["start"]["streamSid"]
            client.stream_sid = self.stream_sid
            logger.info(f"Twilio stream started: {self.stream_sid}")
            await client.on_stream_start()

        elif event == "media":
            payload = data["media"]["payload"]
            chunk = base64.b64decode(payload)
            self._inbound_chunks.append(chunk)
            self.audio_accumulator.extend(chunk)

            if len(self.audio_accumulator) >= MIN_CHUNK_SIZE:
                await self._flush_audio(client)

        elif event == "stop":
            logger.info("Twilio stream stopped")

    async def _flush_audio(self, client: IRealtimeAgentClient) -> None:
        if not self.audio_accumulator:
            return

        audio_b64 = base64.b64encode(bytes(self.audio_accumulator)).decode()
        self.audio_accumulator.clear()
        # Each provider adapter converts µ-law 8kHz to its native format internally
        await client.send_audio(audio_b64)

    async def _handle_provider_event(self, data: dict) -> None:
        """
        Route provider events back to Twilio.
        No provider checks — adapters pre-convert audio to g711_ulaw when is_twilio=True.
        """
        event_type = data.get("type")

        if event_type == "response.audio.delta":
            try:
                audio_bytes = base64.b64decode(data["delta"])
                self._outbound_chunks.append(audio_bytes)
                await self._send_audio_to_twilio(audio_bytes)
            except Exception as e:
                logger.error(f"Error processing audio delta: {e}")

        elif event_type in ["input_audio_buffer.speech_started", "interruption"]:
            await self._clear_twilio_buffer()

        elif event_type == "error":
            logger.error(f"Provider Error: {data}")

    async def _send_audio_to_twilio(self, audio_bytes: bytes) -> None:
        if self.stream_sid and self.twilio_ws:
            try:
                await self.twilio_ws.send_json(
                    {
                        "event": "media",
                        "streamSid": self.stream_sid,
                        "media": {"payload": base64.b64encode(audio_bytes).decode()},
                    }
                )
            except Exception as e:
                logger.error(f"Twilio send error: {e}")

    async def _clear_twilio_buffer(self) -> None:
        """Clear Twilio playback buffer on interruption."""
        if self.stream_sid and self.twilio_ws:
            await self.twilio_ws.send_json(
                {
                    "event": "clear",
                    "streamSid": self.stream_sid,
                }
            )

    async def _save_recordings(self, duration: float) -> None:
        """Write WAV files and POST metadata to the Django API."""
        connection_key = self.realtime_agent_chat_data.connection_key

        for recording_type, chunks in [
            ("inbound", self._inbound_chunks),
            ("outbound", self._outbound_chunks),
        ]:
            if not chunks:
                continue
            raw = b"".join(chunks)
            wav_bytes = _build_ulaw_wav(raw)
            await self._post_recording(
                connection_key=connection_key,
                recording_type=recording_type,
                wav_bytes=wav_bytes,
                duration=duration,
            )

        await self._patch_agent_chat(
            connection_key=connection_key,
            duration=duration,
            end_reason=self._end_reason,
        )

    async def _post_recording(
        self,
        connection_key: str,
        recording_type: str,
        wav_bytes: bytes,
        duration: float,
    ) -> None:
        url = f"{self.django_api_base_url}/conversation-recordings/"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    headers={"Host": "localhost", "X-API-Key": self.django_api_key},
                    data={
                        "connection_key": connection_key,
                        "recording_type": recording_type,
                        "duration_seconds": str(round(duration, 2)),
                    },
                    files={"file": (f"{connection_key}_{recording_type}.wav", io.BytesIO(wav_bytes), "audio/wav")},
                    timeout=30.0,
                )
                if not resp.is_success:
                    logger.warning(
                        f"Failed to save {recording_type} recording: {resp.status_code} {resp.text}"
                    )
                else:
                    logger.info(f"Saved {recording_type} recording for {connection_key}")
        except Exception as e:
            logger.error(f"Error posting {recording_type} recording: {e}")

    async def _patch_agent_chat(
        self, connection_key: str, duration: float, end_reason: str
    ) -> None:
        url = f"{self.django_api_base_url}/realtime-agent-chats/end/"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    headers={"Host": "localhost", "X-API-Key": self.django_api_key},
                    json={
                        "connection_key": connection_key,
                        "duration_seconds": round(duration, 2),
                        "end_reason": end_reason,
                    },
                    timeout=10.0,
                )
                if not resp.is_success:
                    logger.warning(
                        f"Failed to update agent chat metadata: {resp.status_code} {resp.text}"
                    )
        except Exception as e:
            logger.error(f"Error updating agent chat metadata: {e}")
