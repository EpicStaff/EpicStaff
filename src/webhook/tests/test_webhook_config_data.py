import json
from app.core.settings import settings


def test_tunnel_config_channel():
    grok_configs = {
        "ngrok_configs": [
            {
                "name": "test",
                "auth_token": "...",
                "region": "eu",
            },
        ]
    }

    from redis import Redis

    r = Redis(host="localhost", port=6379, password="redis_password")
    data = json.dumps(grok_configs)
    r.publish(settings.REDIS_TUNNEL_CONFIG_CHANNEL, data)
