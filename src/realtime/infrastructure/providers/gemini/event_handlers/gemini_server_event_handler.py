import asyncio
import audioop
import base64
import json
import uuid
from typing import Optional

from loguru import logger

from infrastructure.persistence.database import save_realtime_session_item_to_db


class GeminiServerEventHandler:
    """
    Translates Gemini LiveServerMessage objects into OpenAI-compatible frontend events.
    Mirrors the ElevenLabs server event handler pattern so the frontend requires no changes.
    """

    def __init__(self, client):
        from infrastructure.providers.gemini.gemini_realtime_agent_client import (
            GeminiRealtimeAgentClient,
        )

        self.client: GeminiRealtimeAgentClient = client

        self._current_response_id: Optional[str] = None
        self._current_item_id: Optional[str] = None
        self._current_user_item_id: Optional[str] = None
        self._current_output_index = 0
        self._assistant_output_index = 0
        self._current_transcript = ""
        self._discarding_audio = False  # True after client cancel, until Gemini confirms

    def reset(self) -> None:
        self._current_response_id = None
        self._current_item_id = None
        self._current_user_item_id = None
        self._current_output_index = 0
        self._assistant_output_index = 0
        self._current_transcript = ""
        self._discarding_audio = False

    async def _send_to_client(self, payload: dict) -> None:
        if "event_id" not in payload:
            payload["event_id"] = f"evt_{uuid.uuid4().hex[:16]}"
        await self.client.send_client(payload)

    async def _ensure_response_exists(self) -> None:
        if not self._current_response_id:
            self._current_response_id = f"resp_{uuid.uuid4().hex[:10]}"
            self._current_output_index = 0

            if not self._current_user_item_id:
                self._current_user_item_id = f"msg_user_{uuid.uuid4().hex[:10]}"
                await self._send_to_client(
                    {
                        "type": "conversation.item.created",
                        "item": {
                            "id": self._current_user_item_id,
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_audio", "transcript": None}],
                        },
                    }
                )

            await self._send_to_client(
                {
                    "type": "response.created",
                    "response": {
                        "id": self._current_response_id,
                        "object": "realtime.response",
                        "status": "in_progress",
                        "output": [],
                    },
                }
            )

    async def _ensure_assistant_item(self) -> None:
        await self._ensure_response_exists()

        if not self._current_item_id:
            self._current_item_id = f"msg_{uuid.uuid4().hex[:10]}"
            self._assistant_output_index = self._current_output_index

            agent_item = {
                "id": self._current_item_id,
                "type": "message",
                "role": "assistant",
                "status": "in_progress",
                "content": [{"type": "audio", "transcript": ""}],
            }

            await self._send_to_client(
                {
                    "type": "response.output_item.added",
                    "response_id": self._current_response_id,
                    "output_index": self._assistant_output_index,
                    "item": agent_item,
                }
            )

            await self._send_to_client(
                {"type": "conversation.item.created", "item": agent_item}
            )

            self._current_output_index += 1

    async def handle_event(self, response) -> None:
        """Handle a LiveServerMessage from the Gemini SDK."""
        try:
            if response.setup_complete is not None:
                await self._handle_setup_complete()

            if response.server_content is not None:
                await self._handle_server_content(response.server_content)

            if response.tool_call is not None:
                await self._handle_tool_call(response.tool_call)

            await save_realtime_session_item_to_db(
                data={"type": "gemini_event", "raw": str(response)},
                connection_key=self.client.connection_key,
                org_id=self.client.org_id,
                user_id=self.client.user_id,
            )
        except Exception as e:
            logger.exception(f"Gemini server event handler error: {e}")

    async def _handle_setup_complete(self) -> None:
        await self._send_to_client(
            {
                "type": "session.created",
                "session": {
                    "id": f"gemini_{uuid.uuid4().hex[:16]}",
                    "object": "realtime.session",
                    "provider": "gemini",
                },
            }
        )

    async def _handle_server_content(self, server_content) -> None:
        if server_content.interrupted:
            await self._handle_interrupted()
            return

        if server_content.model_turn:
            for part in server_content.model_turn.parts:
                if part.inline_data and part.inline_data.data:
                    await self._handle_audio_part(part.inline_data.data)
                elif part.text:
                    await self._handle_text_part(part.text)

        if server_content.output_transcription:
            text = getattr(server_content.output_transcription, "text", "") or ""
            if text:
                await self._handle_output_transcription(text)

        if server_content.input_transcription:
            text = getattr(server_content.input_transcription, "text", "") or ""
            if text:
                await self._handle_input_transcription(text)

        if server_content.turn_complete:
            await self._handle_turn_complete()

    async def _handle_audio_part(self, audio_bytes: bytes) -> None:
        """audio_bytes is raw 16-bit PCM at 24kHz from Gemini."""
        if self._discarding_audio:
            return
        await self._ensure_assistant_item()

        if self.client.is_twilio:
            audio_b64 = self._pcm24k_to_ulaw8k(audio_bytes)
        else:
            # Browser expects 24kHz PCM — pass through as-is
            audio_b64 = base64.b64encode(audio_bytes).decode()

        await self._send_to_client(
            {
                "type": "response.audio.delta",
                "response_id": self._current_response_id,
                "item_id": self._current_item_id,
                "output_index": self._assistant_output_index,
                "content_index": 0,
                "delta": audio_b64,
            }
        )

    def _pcm24k_to_ulaw8k(self, audio_bytes: bytes) -> str:
        """Convert raw PCM 24kHz bytes → base64 µ-law 8kHz for Twilio."""
        pcm8k, self.client._resample_state_out = audioop.ratecv(
            audio_bytes, 2, 1, 24000, 8000, self.client._resample_state_out
        )
        return base64.b64encode(audioop.lin2ulaw(pcm8k, 2)).decode()

    async def _handle_output_transcription(self, text: str) -> None:
        """Handle output_transcription from Gemini (requires output_audio_transcription config)."""
        await self._ensure_assistant_item()
        self._current_transcript += text

        await self._send_to_client(
            {
                "type": "response.audio_transcript.delta",
                "response_id": self._current_response_id,
                "item_id": self._current_item_id,
                "output_index": self._assistant_output_index,
                "content_index": 0,
                "delta": text,
            }
        )

    async def _handle_text_part(self, text: str) -> None:
        """Handle text parts in model_turn (fallback for non-audio response modes)."""
        await self._ensure_assistant_item()

    async def _handle_turn_complete(self) -> None:
        rid = self._current_response_id
        iid = self._current_item_id
        idx = self._assistant_output_index

        if rid:
            await self._send_to_client(
                {
                    "type": "response.audio_transcript.done",
                    "response_id": rid,
                    "item_id": iid,
                    "output_index": idx,
                    "content_index": 0,
                    "transcript": self._current_transcript,
                }
            )
            await self._send_to_client(
                {
                    "type": "response.audio.done",
                    "response_id": rid,
                    "item_id": iid,
                    "output_index": idx,
                    "content_index": 0,
                }
            )
            await self._send_to_client(
                {
                    "type": "response.output_item.done",
                    "response_id": rid,
                    "item": {"id": iid, "status": "completed"},
                }
            )
            await self._send_to_client(
                {"type": "response.done", "response": {"id": rid, "status": "completed"}}
            )

        # Save completed model turn to history for context injection on reconnect.
        if self._current_transcript:
            self.client._conversation_history.append(
                {"role": "model", "text": self._current_transcript}
            )

        self._current_response_id = None
        self._current_item_id = None
        self._current_user_item_id = None
        self._current_output_index = 0
        self._assistant_output_index = 0
        self._current_transcript = ""
        self._discarding_audio = False  # Clean turn end — ready for next response

    async def emit_user_text_item(self, text: str) -> None:
        """Echo a frontend-typed message back as the user's chat bubble.

        Unlike spoken input (transcribed server-side via Gemini's own
        input_audio_transcription and delivered through
        `_handle_input_transcription`), a text turn we send via
        send_client_content produces no transcription event -- there is
        nothing to transcribe. We already know the exact text, so
        synthesize the same `conversation.item.created` the frontend
        expects, immediately, instead of leaving the bubble stuck on a
        null transcript.
        """
        self._current_user_item_id = f"msg_user_{uuid.uuid4().hex[:10]}"
        await self._send_to_client(
            {
                "type": "conversation.item.created",
                "item": {
                    "id": self._current_user_item_id,
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            }
        )

    async def _handle_input_transcription(self, text: str) -> None:
        # Save user turn to history for context injection on reconnect.
        self.client._conversation_history.append({"role": "user", "text": text})

        if not self._current_user_item_id:
            self._current_user_item_id = f"msg_user_{uuid.uuid4().hex[:10]}"
            await self._send_to_client(
                {
                    "type": "conversation.item.created",
                    "item": {
                        "id": self._current_user_item_id,
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_audio", "transcript": None}],
                    },
                }
            )

        await self._send_to_client(
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": self._current_user_item_id,
                "content_index": 0,
                "transcript": text,
            }
        )

    async def _handle_interrupted(self) -> None:
        rid = self._current_response_id
        self._current_response_id = None
        self._current_item_id = None
        self._current_output_index = 0
        self._assistant_output_index = 0
        self._current_transcript = ""
        self._discarding_audio = False  # Gemini confirmed interruption — next audio is fresh
        # Rolling buffer in the client event handler already captures this speech.
        # Tell the browser VAD fired — stops audio playback
        await self._send_to_client({"type": "input_audio_buffer.speech_started"})
        if rid:
            await self._send_to_client(
                {"type": "response.cancelled", "response": {"id": rid, "status": "cancelled"}}
            )

    async def handle_client_cancel(self) -> None:
        """Called when the browser sends response.cancel (client-side interruption)."""
        rid = self._current_response_id
        self._current_response_id = None
        self._current_item_id = None
        self._current_output_index = 0
        self._assistant_output_index = 0
        self._current_transcript = ""
        self._discarding_audio = True  # Discard Gemini's remaining audio until it confirms
        # Rolling buffer in the client event handler already captures this speech.
        await self._send_to_client({"type": "input_audio_buffer.speech_started"})
        if rid:
            await self._send_to_client(
                {"type": "response.cancelled", "response": {"id": rid, "status": "cancelled"}}
            )

    async def _handle_tool_call(self, tool_call) -> None:
        await self._ensure_response_exists()

        for func_call in tool_call.function_calls:
            call_id = func_call.id
            tool_name = func_call.name
            args = dict(func_call.args) if func_call.args else {}

            await self._send_to_client(
                {
                    "type": "conversation.item.created",
                    "item": {
                        "id": call_id,
                        "type": "function_call",
                        "status": "in_progress",
                        "name": tool_name,
                        "call_id": call_id,
                        "arguments": "",
                    },
                }
            )

            await self._send_to_client(
                {
                    "type": "response.output_item.added",
                    "response_id": self._current_response_id,
                    "output_index": self._current_output_index,
                    "item": {
                        "id": call_id,
                        "type": "function_call",
                        "name": tool_name,
                        "call_id": call_id,
                        "arguments": "",
                    },
                }
            )

            await self._send_to_client(
                {
                    "type": "response.function_call_arguments.done",
                    "response_id": self._current_response_id,
                    "item_id": call_id,
                    "output_index": self._current_output_index,
                    "call_id": call_id,
                    "name": tool_name,
                    "arguments": json.dumps(args),
                }
            )

            self._current_output_index += 1
            logger.info(f"Gemini: Calling tool {tool_name}")
            # Run as a background task so the receive loop stays unblocked
            # while waiting for the tool result from Redis.
            asyncio.ensure_future(self.client.call_tool(call_id, tool_name, args))

