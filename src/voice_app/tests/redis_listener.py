import asyncio
import redis.asyncio as redis
from app.core.settings import settings


async def listen_to_voice():
    # Connect to Redis
    r = redis.from_url(settings.REDIS_URL)
    pubsub = r.pubsub()

    # Subscribe to all call channels (using psubscribe pattern)
    await pubsub.psubscribe("voice:stream:*")
    print("Listening for voice streams in Redis...")

    try:
        async for message in pubsub.listen():
            if message["type"] == "pmessage":
                channel = message["channel"].decode()
                data_len = len(message["data"])
                print(f"received {data_len} bytes from {channel}")

                # In a real application, data would be sent to Whisper or TTS here
    except KeyboardInterrupt:
        await pubsub.punsubscribe("voice:stream:*")


if __name__ == "__main__":
    asyncio.run(listen_to_voice())
