import asyncio
import json
import base64
from pathlib import Path
import numpy as np
import soundfile as sf
import websockets
from loguru import logger

# Settings
INPUT_AUDIO_WAV = Path(__file__).parent / "../buffer_in_data19-01-19-09-03.wav"
OUTPUT_AUDIO_WAV = Path(__file__).parent / "ai_response_recorded.wav"
WS_URL = "wss://punctiliously-interfraternal-millicent.ngrok-free.dev/voice/stream"  # Set your URL


async def receive_and_save_audio(ws):
    """
    Receives responses from the bridge.
    The bridge forwards OpenAI events to us in Twilio format (media.payload).
    """
    audio_buffer = bytearray()
    logger.info("Starting incoming stream recording...")

    try:
        async for message in ws:
            data = json.loads(message)

            # Capture audio events (Twilio format)
            if data.get("event") == "media":
                payload = data["media"]["payload"]
                mu_law_chunk = base64.b64decode(payload)

                audio_buffer.extend(mu_law_chunk)

            elif data.get("event") == "stop":
                logger.info("Received stop event from the bridge")
                break

    except Exception as e:
        logger.error(f"Error receiving audio: {e}")
    finally:
        if len(audio_buffer) > 0:
            # Convert bytes to a numeric array for soundfile
            audio_array = np.frombuffer(audio_buffer, dtype=np.int16)

            # Save as WAV at 8000 Hz
            sf.write(str(OUTPUT_AUDIO_WAV), audio_array, 8000)
            logger.success(f"Audio saved! File: {OUTPUT_AUDIO_WAV}")
            logger.info(f"Duration: {len(audio_array)/8000:.2f} sec.")
        else:
            logger.warning("Buffer is empty, file not saved.")


async def send_twilio_simulated_audio(ws, file_path: Path):
    """
    File: raw μ-law, 8kHz, mono
    """
    # 1. Read raw μ-law
    with open(file_path, "rb") as f:
        mulaw_data = f.read()

    # 2. start
    await ws.send(
        json.dumps(
            {
                "event": "start",
                "streamSid": "test_sid_123",
                "start": {"accountSid": "AC_test", "callSid": "CA_test"},
            }
        )
    )

    # 3. Send in 20ms chunks (160 bytes)
    chunk_size = 160

    logger.info("Starting audio transmission...")

    for i in range(0, len(mulaw_data), chunk_size):
        chunk = mulaw_data[i : i + chunk_size]
        if not chunk:
            break

        payload = base64.b64encode(chunk).decode()

        await ws.send(json.dumps({"event": "media", "media": {"payload": payload}}))

        await asyncio.sleep(0.02)

    await ws.send(json.dumps({"event": "stop"}))


async def main():
    if not INPUT_AUDIO_WAV.exists():
        logger.error(f"File {INPUT_AUDIO_WAV} not found!")
        return

    async with websockets.connect(WS_URL) as ws:
        logger.info(f"Connected to {WS_URL}")

        # Start reading and writing concurrently
        receiver = asyncio.create_task(receive_and_save_audio(ws))
        sender = asyncio.create_task(send_twilio_simulated_audio(ws, INPUT_AUDIO_WAV))

        await sender
        # Give the AI time to finish speaking after we stop sending the file
        await asyncio.sleep(5)
        await ws.close()
        receiver.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
