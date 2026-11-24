"""Where plugins are served: `PLUGINS_HOST_TEMPLATE`, such as `{id}-app.example.com`.

The template names every plugin host at once: `{id}` is replaced by the plugin's identifier.
It is written as `<prefix>{id}<suffix>.<parent>`: `{id}` sits in the first label, with an
optional prefix and suffix of its own, and the parent is everything after the first label.

- A flat template (`{id}-app.example.com`) puts the plugins beside EpicStaff in its own zone,
  under the zone's free wildcard certificate. The affix tells the plugin hosts from the zone's
  other names.
- A nested template (`{id}.plugins.example.com`) gives the plugins a parent of their own,
  every name under which is a plugin's.

nginx's start-up script (`16-normalize-plugins-enabled.envsh`) and `scripts/envtool.py` apply
the same rules; a change here belongs in both.
"""

import re
from dataclasses import dataclass

from epicstaff_plugin.contracts.manifest import IDENTIFIER_PATTERN

IDENTIFIER_PLACEHOLDER = "{id}"
# The longest identifier the manifest allows: IDENTIFIER_PATTERN is a letter, up to n more
# characters (`{0,n}`) and a final letter or digit. The contract exposes no constant for it.
MAX_IDENTIFIER_LENGTH = int(re.search(r"\{0,(\d+)\}", IDENTIFIER_PATTERN)[1]) + 2
MAX_DNS_LABEL_LENGTH = 63
MAX_DNS_NAME_LENGTH = 253
PLACEHOLDER_SUFFIX = ".invalid"
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
# A label can neither start nor end with a hyphen, so neither can the outer side of an affix.
_PREFIX = re.compile(r"(?:[a-z0-9][a-z0-9-]*)?")
_SUFFIX = re.compile(r"(?:[a-z0-9-]*[a-z0-9])?")
# Hyphens in a label's third and fourth characters are reserved for IDNA (`xn--`).
_RESERVED_HYPHENS = slice(2, 4)


class InvalidHostTemplateError(ValueError):
    """`PLUGINS_HOST_TEMPLATE` breaks one of the rules; the message names which."""


@dataclass(frozen=True)
class PluginHostTemplate:
    prefix: str
    suffix: str
    parent: str

    @classmethod
    def parse(cls, template: str | None) -> "PluginHostTemplate":
        """Read `template`, or say which rule it breaks.

        Raises:
            InvalidHostTemplateError: Not a lower-case template of the shape
                `<prefix>{id}<suffix>.<parent>` whose every host is a valid DNS name.
        """
        template = template or ""
        first_label, _, parent = template.partition(".")
        if template.count(IDENTIFIER_PLACEHOLDER) != 1 or IDENTIFIER_PLACEHOLDER not in first_label:
            raise InvalidHostTemplateError(
                "it must hold {id} exactly once, in its first label, such as {id}-app.example.com"
            )
        prefix, _, suffix = first_label.partition(IDENTIFIER_PLACEHOLDER)
        parent_labels = parent.split(".")
        if len(parent_labels) < 2 or not all(
            _DNS_LABEL.fullmatch(label) for label in parent_labels
        ):
            raise InvalidHostTemplateError(
                "the part after the first label must be a lower-case DNS name of two or more "
                "labels, such as example.com"
            )
        if not _PREFIX.fullmatch(prefix) or not _SUFFIX.fullmatch(suffix):
            raise InvalidHostTemplateError(
                "around {id} only lower-case letters, digits and hyphens may stand, and the "
                "first label may neither start nor end with a hyphen"
            )
        longest_label = len(prefix) + MAX_IDENTIFIER_LENGTH + len(suffix)
        if longest_label > MAX_DNS_LABEL_LENGTH:
            raise InvalidHostTemplateError(
                f"with a {MAX_IDENTIFIER_LENGTH}-character identifier its first label would be "
                f"longer than {MAX_DNS_LABEL_LENGTH} characters"
            )
        if longest_label + 1 + len(parent) > MAX_DNS_NAME_LENGTH:
            raise InvalidHostTemplateError(
                f"with a {MAX_IDENTIFIER_LENGTH}-character identifier a plugin host would be "
                f"longer than {MAX_DNS_NAME_LENGTH} characters"
            )
        if _affixes_reserve_labels(prefix, suffix):
            raise InvalidHostTemplateError(
                "the text around {id} would put hyphens in the third and fourth characters of "
                "some plugin hosts' first label, which DNS reserves for xn-- names"
            )
        return cls(prefix=prefix, suffix=suffix, parent=parent)

    @property
    def is_placeholder(self) -> bool:
        return self.parent.endswith(PLACEHOLDER_SUFFIX)

    @property
    def has_affix(self) -> bool:
        return bool(self.prefix or self.suffix)

    def host(self, identifier: str) -> str:
        return f"{self.prefix}{identifier}{self.suffix}.{self.parent}"

    def plugin_label_middle(self, label: str) -> str | None:
        """The text `label` holds between the prefix and the suffix, or None when it has no
        such text. Says nothing about whether that text is a valid identifier."""
        middle_length = len(label) - len(self.prefix) - len(self.suffix)
        if (
            middle_length <= 0
            or not label.startswith(self.prefix)
            or not label.endswith(self.suffix)
        ):
            return None
        return label[len(self.prefix) : len(self.prefix) + middle_length]

    def covers(self, host: str | None) -> bool:
        """Whether `host` is in the plugin zone, the broad rule every Origin and CORS check uses.

        A host is in the zone when the label directly under the parent is a plugin host's
        shape, prefix and suffix around any non-empty text, or when it is a name under such a
        host. Without an affix every name under the parent is, and so is the parent itself:
        the parent is the plugins' own. With an affix the parent and its other names are not,
        since EpicStaff and other services may live there. Compared in lower case and without
        a trailing dot, as browsers and DNS treat host names.
        """
        if not host:
            return False
        host = host.lower().rstrip(".")
        under_parent = f".{self.parent}"
        if not self.has_affix:
            # Every name, even one with an empty label (`a..parent`, `.parent`).
            return host == self.parent or host.endswith(under_parent)
        if not host.endswith(under_parent):
            return False
        label = host[: -len(under_parent)].rsplit(".", 1)[-1]
        return self.plugin_label_middle(label) is not None

    def shares_site_with(self, host: str) -> bool:
        """Whether `host` and the plugin hosts plausibly form one site, by a rule that needs no
        Public Suffix List.

        Browsers count two hosts as one site when they share a registrable domain: one label
        more than their public suffix (`example.com`, `example.co.uk`). Every registrable
        domain has at least two labels, so hosts of one site always share their last two
        labels or more; this asks only that. It never refuses a working setup. It does catch
        the real mistake, EpicStaff moved to another domain while the template stayed
        (`staff.acme.io` with `{id}-app.acme.com`), and a `.localhost` pair that is two sites
        (`epicstaff.localhost` with `{id}.plugins.localhost`). It cannot tell two
        registrable domains under a two-label public suffix apart (`a.co.uk` and `b.co.uk`).
        """
        host_labels = host.lower().rstrip(".").split(".")
        parent_labels = self.parent.split(".")
        shared = 0
        for host_label, parent_label in zip(
            reversed(host_labels), reversed(parent_labels), strict=False
        ):
            if host_label != parent_label:
                break
            shared += 1
        return shared >= 2


def _affixes_reserve_labels(prefix: str, suffix: str) -> bool:
    """Whether some identifier's first label has reserved hyphens its identifier alone has not.

    Only the label's third and fourth characters count. An identifier starts with a letter and
    ends with a letter or digit, so the affixes decide those two characters as follows: a prefix
    of four or more characters holds them itself; a three- or two-character prefix puts the
    identifier's first, always a letter, in one of them; a one-character prefix shifts the
    identifier's second and third (`a--b` becomes `xa--b`); without a prefix they are the
    identifier's own, unless a two-character identifier leaves them to the suffix.
    """
    if len(prefix) >= 4:
        return prefix[_RESERVED_HYPHENS] == "--"
    if len(prefix) == 1:
        return True
    if not prefix:
        return suffix.startswith("--")
    return False
