import asyncio
import json
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from src.shared.models import RealtimeAgentChatData

from domain.models.chat_mode import ChatMode
from domain.ports.i_chat_mode_controller import IChatModeController
from domain.ports.i_realtime_agent_client import IRealtimeAgentClient
from domain.ports.i_summarization_client import ISummarizationClient
from domain.ports.i_transcription_client import ITranscriptionClient
from domain.ports.i_transcription_client_factory import ITranscriptionClientFactory
from domain.services.chat_buffer import ChatSummarizedBuffer
from domain.services.summarize_buffer import ChatSummarizedBufferClient
from infrastructure.providers.factory import RealtimeAgentClientFactory
from application.tool_manager_service import ToolManagerService
from utils.shorten import shorten_dict
from utils.tokenizer import Tokenizer


class ConversationService(IChatModeController):
    """
    Use case: manages a browser WebSocket real-time conversation session.
    Implements IChatModeController so StopAgentToolExecutor can switch modes
    without a circular import.
    Zero provider-specific branching in the main message loop.
    """

    def __init__(
        self,
        client_websocket: WebSocket,
        realtime_agent_chat_data: RealtimeAgentChatData,
        instructions: str,
        tool_manager_service: ToolManagerService,
        connections: dict,
        factory: RealtimeAgentClientFactory,
        summ_client: ISummarizationClient,
        transcription_client_factory: ITranscriptionClientFactory,
    ):
        self.client_websocket = client_websocket
        self.realtime_agent_chat_data = realtime_agent_chat_data
        self.instructions = instructions
        self.tool_manager_service = tool_manager_service
        self.connections = connections
        self.factory = factory
        self.summ_client = summ_client
        self.transcription_client_factory = transcription_client_factory
        self.wake_word = realtime_agent_chat_data.wake_word
        self.current_chat_mode = ChatMode.CONVERSATION

        # ElevenLabs handles VAD/transcription internally — StopAgent not supported
        chat_mode_controller = (
            None if realtime_agent_chat_data.rt_provider == "elevenlabs" else self
        )
        self.tool_manager_service.register_tools_from_rt_agent_chat_data(
            realtime_agent_chat_data=realtime_agent_chat_data,
            chat_mode_controller=chat_mode_controller,
        )

    # ------------------------------------------------------------------
    # IChatModeController
    # ------------------------------------------------------------------

    def set_chat_mode(self, mode: ChatMode) -> None:
        self.current_chat_mode = mode

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def execute(self):
        try:
            subprotocols = self.client_websocket.scope.get("subprotocols", [])
            await self.client_websocket.accept(
                subprotocol=subprotocols[0] if subprotocols else None
            )

            rt_agent_client_task = None
            rt_transcription_client_task = None

            buffer, summ_buffer_client = self._initialize_buffer(
                max_buffer_tokens=2000, max_chunks_tokens=4000
            )

            rt_tools = await self.tool_manager_service.get_realtime_tool_models(
                connection_key=self.realtime_agent_chat_data.connection_key
            )

            rt_agent_client: IRealtimeAgentClient = self.factory.create(
                config=self.realtime_agent_chat_data,
                rt_tools=rt_tools,
                instructions=self.instructions,
                tool_manager_service=self.tool_manager_service,
                on_server_event=self.client_websocket.send_json,
                is_twilio=False,
            )

            rt_transcription_client = self._maybe_create_transcription_client(buffer)

            await rt_agent_client.connect()
            if rt_transcription_client is not None:
                await rt_transcription_client.connect()

            self.connections[self.client_websocket] = (
                rt_agent_client,
                rt_transcription_client,
            )
            rt_agent_client_task = asyncio.create_task(
                rt_agent_client.handle_messages()
            )
            if rt_transcription_client is not None:
                rt_transcription_client_task = asyncio.create_task(
                    rt_transcription_client.handle_messages()
                )

            logger.info("WebSocket connection established")

            previous_input = ""
            wake_words: list[str] = [
                w.strip("!?., ") for w in self.wake_word.lower().split()
            ]

            while True:
                if (
                    self.current_chat_mode == ChatMode.LISTEN
                    and rt_transcription_client is not None
                ):
                    client = rt_transcription_client
                    last_input: list[str] = buffer.get_last_input()

                    if last_input != previous_input:
                        previous_input = last_input
                        if any(trigger in last_input for trigger in wake_words):
                            final_buffer = buffer.get_final_buffer()

                            await rt_agent_client.send_conversation_item_to_server(
                                final_buffer
                            )
                            await rt_agent_client.request_response()

                            buffer.flush()
                            self.current_chat_mode = ChatMode.CONVERSATION

                    if not buffer.check_free_buffer():
                        logger.debug("Starting summarization of the buffer process...")
                        await summ_buffer_client.summarize_buffer()

                else:
                    client = rt_agent_client

                if rt_agent_client_task is not None and rt_agent_client_task.done():
                    logger.info(
                        f"RT agent session closed — reconnecting ({self.realtime_agent_chat_data.rt_provider})..."
                    )
                    try:
                        rt_agent_client.server_event_handler.reset()
                        await rt_agent_client.connect()
                        rt_agent_client_task = asyncio.create_task(
                            rt_agent_client.handle_messages()
                        )
                        await rt_agent_client.replay_audio_buffer()
                    except Exception as e:
                        logger.error(f"RT agent reconnect failed: {e}")
                        break

                try:
                    message: dict = await self.client_websocket.receive_json()
                    if message.get("type") != "input_audio_buffer.append":
                        logger.debug(f"Received message: {shorten_dict(message)}")

                    response = await client.process_message(message)
                    if response:
                        logger.debug(f"Sending response: {response}")
                        await self.client_websocket.send_json(response)

                except json.JSONDecodeError:
                    logger.error("Invalid JSON format")
                    await self.client_websocket.send_json(
                        {"type": "error", "message": "Invalid JSON format"}
                    )

                except WebSocketDisconnect:
                    raise

                except Exception as e:
                    logger.exception(f"Error processing message: {e}")
                    await self.client_websocket.send_json(
                        {"type": "error", "message": str(e)}
                    )

        except WebSocketDisconnect:
            logger.info("Client disconnected")
        except Exception:
            logger.exception("Unexpected exception")
        finally:
            if rt_agent_client_task is not None and not rt_agent_client_task.done():
                rt_agent_client_task.cancel()

            if (
                rt_transcription_client_task is not None
                and not rt_transcription_client_task.done()
            ):
                rt_transcription_client_task.cancel()

            if self.client_websocket in self.connections:
                await rt_agent_client.close()
                del self.connections[self.client_websocket]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _initialize_buffer(
        self, max_buffer_tokens: int, max_chunks_tokens: int, model: str = "gpt-4o"
    ) -> tuple[ChatSummarizedBuffer, ChatSummarizedBufferClient]:
        tokenizer = Tokenizer(model)
        buffer = ChatSummarizedBuffer(tokenizer, max_buffer_tokens, max_chunks_tokens)
        summ_buffer_client = ChatSummarizedBufferClient(
            buffer=buffer, summ_client=self.summ_client
        )
        return buffer, summ_buffer_client

    def _maybe_create_transcription_client(
        self, buffer: ChatSummarizedBuffer
    ) -> ITranscriptionClient | None:
        return self.transcription_client_factory.create(
            config=self.realtime_agent_chat_data,
            on_server_event=self.client_websocket.send_json,
            buffer=buffer,
        )
