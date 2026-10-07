import json

from django.core.files.uploadedfile import SimpleUploadedFile
from plugins.models import PluginResource
from plugins.samples.zip_builder import sample_files

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


def chat_admin_manifest(refs: dict[str, int]) -> dict:
    """plugin.json of the chat-admin sample, for the ids its export command printed."""
    return {
        "format_version": 1,
        "bridge": 2,
        "id": "chat-admin",
        "version": "0.1.0",
        "name": "Chat Admin",
        "description": "A support chat bot with a page that lists its conversations.",
        "icon": "ui/icon.svg",
        "ui": {"entry": "ui/index.html"},
        "secret_slots": [{"name": "OPENAI_API_KEY", "description": "OpenAI API key."}],
        "secret_bindings": [
            {
                "entity": "LLMConfig",
                "ref": refs["LLMConfig"],
                "field": "api_key_secret",
                "slot": "OPENAI_API_KEY",
            }
        ],
        "access": [
            {
                "alias": "chat",
                "type": "flow",
                "ref": refs["Flow"],
                "actions": ["run", "sessions.read", "sessions.stop"],
            },
            {
                "alias": "conversations",
                "type": "key_value_table",
                "ref": refs["KeyValueTable"],
                "actions": ["read"],
            },
        ],
    }


def chat_admin_files(resources: dict, manifest: dict) -> dict[str, bytes]:
    """A chat-admin bundle; its page is the chat-bot sample's, which is all a test needs."""
    page = sample_files()
    return {
        "plugin.json": json.dumps(manifest).encode(),
        "resources.json": json.dumps(resources).encode(),
        "ui/index.html": page["ui/index.html"],
        "ui/icon.svg": page["ui/icon.svg"],
    }
