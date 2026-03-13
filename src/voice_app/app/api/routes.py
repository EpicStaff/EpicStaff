import json
import asyncio
import base64
import httpx
from fastapi import APIRouter, WebSocket, Response
from loguru import logger

from app.client.realtime_client import RealtimeClient, TurnDetectionMode
from app.core.settings import settings

router = APIRouter(prefix="/voice", tags=["voice"])

INIT_API_URL = settings.INIT_API_URL
AI_WS_URL = settings.AI_WS_URL
AGENT_ID = settings.VOICE_AGENT_ID

SUBPROTOCOL = "openai-beta.realtime-v1"


@router.post("")
async def incoming_call():
    logger.info("Incoming call received")
    return Response(
        content="""
        <Response>
          <Connect>
            <Stream url="wss://punctiliously-interfraternal-millicent.ngrok-free.dev/voice/stream" />
          </Connect>
        </Response>
        """,
        media_type="application/xml",
    )


@router.websocket("/stream")
async def websocket_bridge(twilio_ws: WebSocket):
    await twilio_ws.accept()
    logger.info("Twilio WebSocket accepted")

    stream_sid = None
    ai_task = None

    # BUFFER SETTINGS
    # G.711 u-law is 8000 bytes/second.
    # 160 bytes = 20ms (Twilio default)
    # 960 bytes = 120ms (Target size to reduce overhead)
    # 1920 bytes = 240 ms
    MIN_CHUNK_SIZE = 960
    audio_accumulator = bytearray()

    # 1. Initialize Connection to Relay/AI Service
    async with httpx.AsyncClient() as http_client:
        try:
            resp = await http_client.post(
                settings.INIT_API_URL,
                json={
                    "agent_id": settings.VOICE_AGENT_ID,
                    "config": {
                        "input_audio_format": "g711_ulaw",
                        "output_audio_format": "g711_ulaw",
                    },
                },
            )
            if resp.status_code >= 400:
                logger.error(f"Init failed: {resp.status_code} {resp.text}")
                await twilio_ws.close()
                return

            conn_key = resp.json().get("connection_key")
        except Exception as e:
            logger.error(f"Init connection error: {e}")
            await twilio_ws.close()
            return

    # 2. Define Callbacks
    async def handle_ai_audio(audio_bytes: bytes):
        if stream_sid:
            payload = {
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": base64.b64encode(audio_bytes).decode("utf-8")},
            }
            await twilio_ws.send_text(json.dumps(payload))

    async def handle_ai_interrupt():
        if stream_sid:
            # Clear Twilio's audio buffer
            await twilio_ws.send_text(
                json.dumps({"event": "clear", "streamSid": stream_sid})
            )

    # 3. Instantiate Client
    ai_client = RealtimeClient(
        api_key="relay-override",
        base_url=f"{settings.AI_WS_URL}?connection_key={conn_key}",
        voice="alloy",
        turn_detection_mode=TurnDetectionMode.SERVER_VAD,
        audio_format="g711_ulaw",
        on_audio_delta=handle_ai_audio,
        on_interrupt=handle_ai_interrupt,
    )

    # 4. Start Interaction
    try:
        await ai_client.connect()
        logger.success("Connected to AI Realtime API")

        ai_task = asyncio.create_task(ai_client.handle_messages())

        # 5. Handle Incoming Twilio Messages with Buffering
        async for message in twilio_ws.iter_text():
            data = json.loads(message)

            if data.get("event") == "media":
                # A) Decode and Append
                chunk = base64.b64decode(data["media"]["payload"])
                audio_accumulator.extend(chunk)

                # B) Check Threshold (Buffer Logic)
                if len(audio_accumulator) >= MIN_CHUNK_SIZE:
                    await ai_client.stream_audio(bytes(audio_accumulator))
                    audio_accumulator.clear()

            elif data.get("event") == "start":
                stream_sid = data["start"]["streamSid"]
                logger.info(f"Stream Started: {stream_sid}")

            elif data.get("event") == "stop":
                logger.info("Stream Stopped")
                # Flush remaining bytes if any
                if len(audio_accumulator) > 0:
                    await ai_client.stream_audio(bytes(audio_accumulator))
                break

    except Exception as e:
        logger.error(f"Bridge Error: {e}")
    finally:
        await ai_client.close()

        if ai_task and not ai_task.done():
            ai_task.cancel()
            try:
                await ai_task
            except asyncio.CancelledError:
                pass

        try:
            await twilio_ws.close()
        except Exception as e:
            logger.error(f"await twilio_ws.close() had a error {e}")
            pass
