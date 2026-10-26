"""`epicstaff-plugin schema`: write the manifest JSON Schema."""

from pathlib import Path

from epicstaff_plugin.cli.output import EXIT_OK, UsageError
from epicstaff_plugin.contracts.manifest import render_manifest_json_schema


def schema(output: Path) -> int:
    try:
        output.write_text(render_manifest_json_schema(), encoding="utf-8")
    except OSError as error:
        raise UsageError(f"cannot write {output}: {error}") from None
    print(f"wrote {output}")
    return EXIT_OK
