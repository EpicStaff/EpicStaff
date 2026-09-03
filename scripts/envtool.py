"""
Generate `.env` file from env.yaml

Usage:
    python scripts/envtool.py        # generate `.env` file with variables defaults for production
    python scripts/envtool.py --dev  # generate `.env` file with variables defaults for development

Requires: PyYAML  (pip install pyyaml)
"""

import argparse
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml

BASE_DIR = Path(__file__).resolve().parent

BANNER = """
# GENERATED FROM: {schema_file}
# GENERATED AT: {timestamp}
"""
GROUP_TITLE_PATTERN = """
# ==================================================================================================
# {group}
# ==================================================================================================
"""
REQUIRED_VARIABLE_PATTERN = "# {name}=<enter your value>\n"
DEFAULT_VARIABLE_PATTERN = "{name}={default}\n"


def load_schema(schema_file: Path) -> dict:
    return yaml.safe_load(schema_file.read_bytes())

def render_description(text: str) -> str:
    lines = textwrap.wrap(
        text,
        width=100,
        initial_indent="# ",
        subsequent_indent="# ",
        break_long_words=False,
        break_on_hyphens=False,
    )
    return "\n" + "\n".join(lines) + "\n"

def generate_env_file(schema: dict, target: Literal["prod", "dev"], schema_file: Path, env_file: Path):
    content = [
        BANNER.format(
            schema_file=schema_file.relative_to(BASE_DIR.parent),
            timestamp=datetime.now(),
        )
    ]
    for group, variables in schema["groups"].items():
        content.append(GROUP_TITLE_PATTERN.format(group=group.title()))

        for name, declaration in variables["vars"].items():
            description = declaration.get("description")

            if description:
                content.append(render_description(description))

            default = d.get(target) if isinstance(d := declaration.get("default"), dict) else d

            if default is None:
                content.append(REQUIRED_VARIABLE_PATTERN.format(name=name))
            else:
                content.append(DEFAULT_VARIABLE_PATTERN.format(name=name, default=default))

    content = "".join(content)
    env_file.write_text(content)

def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--dev",
        action="store_true",
        help="Generate `.env` with variable defaults for development.",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Env file path."
    )
    parser.add_argument(
        "--schema-file",
        default="env.yaml",
        help="Schema file path."
    )

    args = parser.parse_args()
    target = "prod" if not args.dev else "dev"
    schema_file = BASE_DIR / args.schema_file
    env_file = BASE_DIR / args.env_file

    schema = load_schema(schema_file)
    generate_env_file(schema, target, schema_file, env_file)


if __name__ == '__main__':
    main()