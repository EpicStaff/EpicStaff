# Scrubs plaintext credentials from Session.graph_schema rows written before
# SecretResolver landed. See docs/superpowers/plans/
# 2026-07-30-secret-management-secret-resolver.md Task 7 and the design doc §7.1.

from django.db import migrations

# Keyed on field name, not on GraphData's shape: one pass then covers subgraph
# copies and stays correct if the payload models change.
_SECRET_FIELD_NAMES = frozenset(
    {"api_key", "auth", "rt_api_key", "transcript_api_key"}
)


def _needs_scrub(node) -> bool:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _SECRET_FIELD_NAMES and value is not None:
                return True
            if _needs_scrub(value):
                return True
    elif isinstance(node, list):
        return any(_needs_scrub(item) for item in node)
    return False


def _scrub_secrets(node):
    """Return a copy of `node` with every secret-named value nulled at any depth."""
    if isinstance(node, dict):
        return {
            key: None if key in _SECRET_FIELD_NAMES else _scrub_secrets(value)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_scrub_secrets(item) for item in node]
    return node


def scrub_graph_schemas(apps, schema_editor):
    Session = apps.get_model("tables", "Session")
    scrubbed_count = 0
    for session in Session.objects.exclude(graph_schema={}).iterator():
        if not _needs_scrub(session.graph_schema):
            continue
        session.graph_schema = _scrub_secrets(session.graph_schema)
        session.save(update_fields=["graph_schema"])
        scrubbed_count += 1
    if scrubbed_count:
        print(f"Scrubbed plaintext credentials from {scrubbed_count} session(s).")


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0210_embeddingconfig_api_key_secret_and_more"),
    ]

    operations = [
        migrations.RunPython(
            scrub_graph_schemas,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
