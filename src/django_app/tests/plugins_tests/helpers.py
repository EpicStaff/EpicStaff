import json

from django.core.files.uploadedfile import SimpleUploadedFile
from plugins.models import PluginResource

PLUGINS_URL = "/api/plugins/"
INSPECT_URL = "/api/plugins/inspect/"
INSTALL_URL = "/api/plugins/install/"
SECRETS = {"OPENAI_API_KEY": "sk-plugin-test-key"}


def upload(content: bytes, name: str = "chat-bot-plugin.zip") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="application/zip")


def install_payload(content: bytes, secrets: dict | None = None) -> dict:
    """Multipart body of POST /api/plugins/install/."""
    return {"file": upload(content), "secrets": json.dumps(SECRETS if secrets is None else secrets)}


def plugin_url(plugin, action: str | None = None) -> str:
    return f"{PLUGINS_URL}{plugin.pk}/" + (f"{action}/" if action else "")


def registered_ids(plugin, resource_type: str) -> list[int]:
    """Object ids the plugin's registry links for one resource type."""
    return sorted(
        PluginResource.objects.filter(plugin=plugin, resource_type=resource_type).values_list(
            "object_id", flat=True
        )
    )
