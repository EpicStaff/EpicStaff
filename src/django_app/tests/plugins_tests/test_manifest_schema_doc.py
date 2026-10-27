from pathlib import Path

from epicstaff_plugin.contracts.manifest import render_manifest_json_schema

SCHEMA_DOC = Path(__file__).resolve().parents[4] / "docs" / "plugins" / "reference" / "manifest.schema.json"


def test_the_published_schema_equals_the_schema_generated_from_the_model():
    # Regenerate with: uv run --frozen --project src/plugin_sdk epicstaff-plugin schema
    #   --out docs/plugins/reference/manifest.schema.json
    assert SCHEMA_DOC.read_text(encoding="utf-8") == render_manifest_json_schema()
