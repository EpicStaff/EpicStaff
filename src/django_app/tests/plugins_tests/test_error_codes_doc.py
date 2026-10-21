"""docs/plugins/reference/error-codes.md lists exactly the codes the plugin platform defines."""

import inspect
import re
from pathlib import Path

from plugins import exceptions
from utils.exceptions import CustomAPIExeption

ERROR_CODES_DOC = Path(__file__).resolve().parents[4] / "docs" / "plugins" / "reference" / "error-codes.md"
# The client codes nginx answers with for each gateway refusal; nginx owns the mapping.
GATEWAY_CODES = {"login_required", "not_found", "rate_limited", "request_too_large", "plugin_unavailable", "forbidden"}
_CODE_CELL = re.compile(r"^\| `([a-z_]+)` \|", re.MULTILINE)


def _section(heading: str) -> str:
    text = ERROR_CODES_DOC.read_text(encoding="utf-8")
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def _documented(heading: str) -> list[str]:
    return _CODE_CELL.findall(_section(heading))


def _defined_codes() -> set[str]:
    return {
        error.default_code
        for _, error in inspect.getmembers(exceptions, inspect.isclass)
        if issubclass(error, CustomAPIExeption)
        and error.__module__ == exceptions.__name__
        and "default_code" in vars(error)
    }


def test_every_plugin_error_code_is_documented_once_and_nothing_else():
    documented = _documented("Plugin API codes")

    assert len(documented) == len(set(documented))
    assert set(documented) == _defined_codes()


def test_every_gateway_code_is_documented():
    assert set(_documented("Gateway codes")) == GATEWAY_CODES
