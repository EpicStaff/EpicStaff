"""The PLUGINS_HOST_TEMPLATE cases django_app, envtool and nginx share (src/shared)."""

from pathlib import Path

CASES_FILE = Path(__file__).resolve().parents[3] / "shared" / "plugin_host_template_cases.txt"
EMPTY = "<empty>"


def _cases():
    for line in CASES_FILE.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        verdict, _, rest = line.partition(" ")
        if verdict == "accept":
            yield verdict, None, rest
        else:
            rule, _, template = rest.partition(" ")
            yield verdict, rule, "" if template == EMPTY else template


ACCEPTED = [template for verdict, _, template in _cases() if verdict == "accept"]
REFUSED = [(template, rule) for verdict, rule, template in _cases() if verdict == "refuse"]
