"""The command-line reference and every command the docs show agree with the parser.

`docs/plugins/reference/cli.md` has one `## \\`epicstaff-plugin <command>\\`` section per command,
naming each of its options and arguments in backticks. Every `epicstaff-plugin ...` line in a
code block of the plugin docs or the sample's README must parse: lines ending in a backslash are
joined, the command runs from the first `epicstaff-plugin` word up to `|`, `&&`, `;`, `>` or `#`,
each `<...>` is a placeholder, and `--help` is valid.
"""

import argparse
import contextlib
import io
import re
import shlex
from pathlib import Path

import pytest

from conftest import REPO_ROOT, WEATHER_SAMPLE
from epicstaff_plugin.cli.main import build_parser

DOCS = REPO_ROOT / "docs" / "plugins"
CLI_REFERENCE = DOCS / "reference" / "cli.md"
COMMAND_HEADING = re.compile(r"^## `epicstaff-plugin ([a-z-]+)`\s*$", re.MULTILINE)
SECTION_END = re.compile(r"^## ", re.MULTILINE)
CODE_SPAN = re.compile(r"`([^`\n]+)`")
FENCE = re.compile(r"^\s*(```|~~~)")
COMMAND_WORD = re.compile(r"(?:^|\s)epicstaff-plugin(?=\s|$)")
PLACEHOLDER = re.compile(r"<[^<>\n]*>")
SHELL_END = re.compile(r"\||&&|;|>|#")
PLACEHOLDER_TOKEN = "PLACEHOLDER"
# A placeholder after one of these options stands for a value its type accepts.
PLACEHOLDER_VALUES = {"--port": "8001", "--host": "127.0.0.1"}


def _commands() -> dict[str, argparse.ArgumentParser]:
    parser = build_parser()
    subcommands = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    return dict(subcommands.choices)


def _names(command: argparse.ArgumentParser) -> list[str]:
    """Every option (all its spellings) and positional argument of a command, without --help."""
    names = []
    for action in command._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        names.extend(action.option_strings or [action.dest])
    return names


def _sections() -> dict[str, str]:
    text = CLI_REFERENCE.read_text(encoding="utf-8")
    sections = {}
    for heading in COMMAND_HEADING.finditer(text):
        rest = text[heading.end() :]
        end = SECTION_END.search(rest)
        sections[heading.group(1)] = rest[: end.start()] if end else rest
    return sections


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """The logical lines of the file's fenced code blocks, with backslash continuations joined."""
    lines = []
    inside = False
    pending, pending_start = "", 0
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if FENCE.match(line):
            inside = not inside
            continue
        if not inside:
            continue
        if not pending:
            pending_start = number
        if line.rstrip().endswith("\\"):
            pending += line.rstrip()[:-1] + " "
            continue
        lines.append((pending_start, pending + line))
        pending = ""
    return lines


def _documented_commands() -> list[tuple[str, str]]:
    pages = sorted(DOCS.rglob("*.md")) + [WEATHER_SAMPLE / "README.md"]
    found = []
    for page in pages:
        for number, line in _code_lines(page):
            if match := COMMAND_WORD.search(line):
                location = f"{page.relative_to(REPO_ROOT)}:{number}"
                found.append((location, line[match.end() :]))
    return found


def _arguments(command_text: str) -> list[str]:
    text = PLACEHOLDER.sub(PLACEHOLDER_TOKEN, command_text)
    if end := SHELL_END.search(text):
        text = text[: end.start()]
    arguments = shlex.split(text)
    return [
        PLACEHOLDER_VALUES.get(arguments[index - 1], argument) if PLACEHOLDER_TOKEN in argument and index else argument
        for index, argument in enumerate(arguments)
    ]


DOCUMENTED_COMMANDS = _documented_commands()


def test_the_reference_documents_every_command_and_nothing_else():
    assert CLI_REFERENCE.is_file(), f"{CLI_REFERENCE.relative_to(REPO_ROOT)} is missing"

    assert sorted(_sections()) == sorted(_commands())


@pytest.mark.parametrize("command", sorted(_commands()))
def test_the_reference_names_every_option_and_argument_of_a_command(command):
    assert CLI_REFERENCE.is_file(), f"{CLI_REFERENCE.relative_to(REPO_ROOT)} is missing"
    section = _sections().get(command, "")
    spans = CODE_SPAN.findall(section)

    missing = [
        name
        for name in _names(_commands()[command])
        if not any(re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", span) for span in spans)
    ]

    assert missing == [], f"epicstaff-plugin {command}: not in backticks in its section of cli.md"


def test_the_docs_show_epicstaff_plugin_commands():
    # The scan below proves nothing if it finds no command at all.
    assert len(DOCUMENTED_COMMANDS) > 5


@pytest.mark.parametrize(
    ("location", "command_text"), DOCUMENTED_COMMANDS, ids=[location for location, _ in DOCUMENTED_COMMANDS]
)
def test_every_command_the_docs_show_parses(location, command_text):
    arguments = _arguments(command_text)
    errors = io.StringIO()

    with contextlib.redirect_stderr(errors), contextlib.redirect_stdout(io.StringIO()):
        try:
            build_parser().parse_args(arguments)
        except SystemExit as exited:
            # `--help` prints and exits 0.
            assert exited.code == 0, f"{location}: epicstaff-plugin {' '.join(arguments)}\n{errors.getvalue()}"


@pytest.mark.parametrize(
    ("command_text", "expected"),
    [
        (" dev <your plugin directory> --runtime-file <downloaded file> --port <backend port or 8001>", ["dev", "PLACEHOLDER", "--runtime-file", "PLACEHOLDER", "--port", "8001"]),
        (" keygen --out <prefix>.key # then keep the key", ["keygen", "--out", "PLACEHOLDER.key"]),
        (" validate weather.esplugin && echo ok", ["validate", "weather.esplugin"]),
        (" schema --out schema.json > /dev/null", ["schema", "--out", "schema.json"]),
    ],
    ids=["placeholders with spaces", "placeholder in a word and a comment", "and", "redirect"],
)
def test_a_documented_command_is_read_as_a_shell_would(command_text, expected):
    assert _arguments(command_text) == expected
