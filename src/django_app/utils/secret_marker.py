"""Syntax of the `epicstaff_secret(<name>)` marker a stored string uses to reference a secret.

A wire contract, duplicated per consumer (agent, crew, knowledge_new): no shared owner.
This is django_app's only production copy: the secret resolver compiles it and the
model-config JSON Schema anchors it, so the served schema and the resolver agree on what
a marker is. `tests/sealed_values.py` keeps the consumers' copy on purpose, so tests check
django_app against an independent one.
"""

# The name is trimmed of surrounding whitespace, holds a non-space character and never
# contains `epicstaff_secret(`: in `epicstaff_secret(epicstaff_secret(inner)` the name is
# `inner`. The shape keeps matching linear on values a caller controls: the name starts
# and ends on a non-space, so a run of whitespace splits between the name and the `\s*`
# around it in one way only, and the name never runs across a later
# `epicstaff_secret(`, so a value repeating an unclosed marker is scanned once rather
# than once per marker. Group 1 is the name.
# ECMA-262 compatible, as a JSON Schema `pattern` must be. One line, so the consumers'
# copies can stay byte-identical to it.
SECRET_MARKER_PATTERN = r"epicstaff_secret\(\s*((?!epicstaff_secret\()[^)\s](?:(?:(?!epicstaff_secret\()[^)])*[^)\s])?)\s*\)"
