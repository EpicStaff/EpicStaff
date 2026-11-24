"""The reserved-hyphen rule of PLUGINS_HOST_TEMPLATE, proved against every short identifier."""

import itertools
import re

import pytest
from epicstaff_plugin.contracts.manifest import IDENTIFIER_PATTERN
from plugins.configuration.host_template import InvalidHostTemplateError, PluginHostTemplate

# Only whether a character is a letter, a digit or a hyphen decides whether a label has hyphens
# in its third and fourth characters, so one of each stands for all of them.
CHARACTER_CLASSES = "a0-"


def _strings(max_length):
    for length in range(max_length + 1):
        for characters in itertools.product(CHARACTER_CLASSES, repeat=length):
            yield "".join(characters)


# Long enough for every position the affixes can shift into the third and fourth characters.
IDENTIFIERS = [text for text in _strings(6) if re.fullmatch(IDENTIFIER_PATTERN, text)]


def _reserved(label):
    return label[2:4] == "--"


def _creates_a_reserved_label(prefix, suffix):
    return any(
        _reserved(prefix + identifier + suffix) and not _reserved(identifier) for identifier in IDENTIFIERS
    )


def _is_label_edge_safe(prefix, suffix):
    return not prefix.startswith("-") and not suffix.endswith("-")


def _accepted(template):
    try:
        PluginHostTemplate.parse(template)
    except InvalidHostTemplateError:
        return False
    return True


def test_a_template_is_refused_exactly_when_its_affixes_put_reserved_hyphens_in_a_label_the_identifier_lacks():
    wrong = [
        (prefix, suffix)
        for prefix in _strings(5)
        for suffix in _strings(3)
        if _is_label_edge_safe(prefix, suffix)
        and _accepted(f"{prefix}{{id}}{suffix}.example.com") == _creates_a_reserved_label(prefix, suffix)
    ]

    assert wrong == []


@pytest.mark.parametrize(
    ("template", "accepted"),
    [
        ("x{id}.example.com", False),
        ("xy{id}.example.com", True),
        ("ab--{id}.example.com", False),
        ("abc--{id}.example.com", True),
        ("{id}--x.example.com", False),
        ("{id}-a--b.example.com", True),
    ],
)
def test_the_reserved_hyphen_rule_by_example(template, accepted):
    assert _accepted(template) is accepted
