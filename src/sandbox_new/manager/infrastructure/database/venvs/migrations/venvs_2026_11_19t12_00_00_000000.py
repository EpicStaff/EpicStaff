import json
import re

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from piccolo.apps.migrations.auto.migration_manager import MigrationManager

ID = "2026-11-19T12:00:00:000000"
VERSION = "1.36.0"
DESCRIPTION = (
    "Move version bounds out of venv library names, and fail the venvs whose "
    "libraries cannot be kept under the current rules"
)

# Frozen copies of the rules a library is held to when this migration was written.
# A migration never imports the domain: the domain moves on, this file must not.
_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
_LIBRARY_NAME_RE = re.compile(rf"{_NAME}(?:\[{_NAME}(?:,{_NAME})*\])?")
_VERSION_RE = re.compile(
    r"([1-9][0-9]*!)?(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*((a|b|rc)(0|[1-9][0-9]*))?"
    r"(\.post(0|[1-9][0-9]*))?(\.dev(0|[1-9][0-9]*))?(\+[a-z0-9]+([-_\.][a-z0-9]+)*)?"
)
# What `str.splitlines` breaks on: each would end the requirement line uv reads.
_LINE_BREAKS = frozenset("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")


async def forwards():
    manager = MigrationManager(migration_id=ID, app_name="venvs", description=DESCRIPTION)

    async def migrate_library_names():
        """Rewrite every venv row whose libraries the current rules would not read.

        A row only reshaped keeps its status: the libraries it built are the same.
        A row whose bound had its dots restored is declared again: uv read `>=1-26` as
        `>=1.post26`, so what it built may lie outside the bound now written, and the
        rebuild installs what was meant. A row that lost an entry is failed with the
        dropped names in `error`, since it can no longer be built as it was declared.
        """
        from manager.infrastructure.database.venvs.tables import VenvTable

        rows = await VenvTable.raw("SELECT id, libs FROM venv").run()
        for row in rows:
            stored = (
                row["libs"] if isinstance(row["libs"], list) else json.loads(row["libs"] or "[]")
            )
            libraries, dropped = _migrate_libraries(stored)
            if not dropped and libraries == stored:
                continue

            if dropped:
                # repr: a refused name can hold a line break, which would split the message.
                error = (
                    "Removed libraries an earlier release accepted and this one refuses: "
                    + ", ".join(repr(name) for name in dropped)
                    + ". Declare them again as a package name, with the version in the "
                    "specification."
                )
                await VenvTable.raw(
                    "UPDATE venv SET libs = {}::jsonb, status = {}, error = {} WHERE id = {}",
                    json.dumps(libraries),
                    "failed",
                    error,
                    row["id"],
                ).run()
            elif _a_bound_was_rewritten(stored):
                await VenvTable.raw(
                    "UPDATE venv SET libs = {}::jsonb, status = {}, error = NULL WHERE id = {}",
                    json.dumps(libraries),
                    "declared",
                    row["id"],
                ).run()
            else:
                await VenvTable.raw(
                    "UPDATE venv SET libs = {}::jsonb WHERE id = {}",
                    json.dumps(libraries),
                    row["id"],
                ).run()

    manager.add_raw(migrate_library_names)
    return manager


def _migrate_libraries(stored: list) -> tuple[list[dict], list[str]]:
    """Bring one venv's stored libraries under the current rules.

    Returns the entries kept, in their stored order, and the stored names of the
    entries dropped because they cannot be kept. A malformed entry, one that is not an
    object or lacks a name, is dropped too rather than raised on: the migration runs
    at start-up, and raising would keep the service from starting at all.

    A venv now takes one entry per package, extras included, so entries an earlier
    release kept apart are merged into the first one: `numpy` and `numpy>=1` both read
    as `numpy` once split, and `requests` next to `requests[socks]` is one package. uv
    built such a venv by honouring every entry at once, which is what the merged entry
    asks for: the union of the extras and every specification joined.
    """
    libraries: list[dict] = []
    dropped: list[str] = []
    position_by_package: dict[str, int] = {}
    for library in stored:
        migrated = _migrate_library(library) if isinstance(library, dict) else None
        if migrated is None:
            dropped.append(_stored_name(library))
            continue

        package = canonicalize_name(migrated["name"].partition("[")[0])
        if package not in position_by_package:
            position_by_package[package] = len(libraries)
            libraries.append(migrated)
            continue

        position = position_by_package[package]
        merged = _merge_libraries(libraries[position], migrated)
        if merged is None:
            dropped.append(_stored_name(library))
            continue
        libraries[position] = merged
    return libraries, dropped


def _stored_name(library: object) -> str:
    """What names a dropped entry in the venv's error: its name, or the entry itself."""
    if isinstance(library, dict) and isinstance(library.get("name"), str):
        return library["name"]
    return str(library)


def _a_bound_was_rewritten(stored: list) -> bool:
    """Whether some stored name held a bound whose dashes become dots.

    Earlier releases canonicalized the bound with the name, so `numpy>=1.26` was
    stored as `numpy>=1-26`, which uv read as `>=1.post26`.
    """
    for library in stored:
        name = library.get("name") if isinstance(library, dict) else None
        if not isinstance(name, str) or _LIBRARY_NAME_RE.fullmatch(name):
            continue
        name_match = _LIBRARY_NAME_RE.match(name)
        if name_match is not None and "-" in name[name_match.end() :]:
            return True
    return False


def _merge_libraries(first: dict, second: dict) -> dict | None:
    """One entry asking for everything both entries for a package asked for.

    The first entry's description and pin are kept, the pin only while the joined
    specification still admits it. None when the two disagree on whether the package
    is a custom library, which no single entry can say.
    """
    if bool(first.get("is_custom")) != bool(second.get("is_custom")):
        return None

    package, first_extras = _split_extras(first["name"])
    _, second_extras = _split_extras(second["name"])
    extras = sorted(set(first_extras) | set(second_extras))
    name = canonicalize_name(package)
    if extras:
        name += f"[{','.join(extras)}]"

    clauses: list[str] = []
    for specification in (first["specification"], second["specification"]):
        if specification and specification not in clauses:
            clauses.append(specification)
    specification = ",".join(clauses)
    if not _specification_is_valid(specification):
        return None

    version = _pin_within(first.get("version"), specification)
    return {**first, "name": name, "specification": specification, "version": version}


def _split_extras(name: str) -> tuple[str, list[str]]:
    """`requests[socks,security]` as `requests` and its canonical extras."""
    package, _, extras = name.partition("[")
    return package, [canonicalize_name(extra) for extra in extras.rstrip("]").split(",") if extra]


def _pin_within(version: object, specification: str) -> str | None:
    """The pin, or None when it is not a version or the specification excludes it:
    the next build stamps it again."""
    if not isinstance(version, str) or _VERSION_RE.fullmatch(version) is None:
        return None
    if not SpecifierSet(specification).contains(version, prereleases=True):
        return None
    return version


def _migrate_library(library: dict) -> dict | None:
    """Return the entry as the current rules accept it, or None when it cannot be kept.

    An entry valid today comes back unchanged. A version bound inside the name moves to
    the specification (`numpy>=1-26` becomes `numpy` with `>=1.26`): earlier releases
    canonicalized the whole name, turning the bound's dots into dashes, so the dots are
    restored. A bound in the name next to a stored specification is joined to it, the
    bound first. A pin the new specification excludes is cleared, and the next build
    stamps it again.

    None when the name is missing or does not parse, holds a URL or a marker, gives a
    specification the current rules refuse even once repaired (`_repair_specification`),
    or gives extras to a custom library.
    """
    name = library.get("name")
    specification = library.get("specification") or ""
    if not isinstance(name, str) or not isinstance(specification, str):
        return None

    if _LIBRARY_NAME_RE.fullmatch(name):
        new_name, bound = name, ""
    else:
        name_match = _LIBRARY_NAME_RE.match(name)
        if name_match is None:
            return None

        bound = name[name_match.end() :].strip()
        if bound.startswith("(") and bound.endswith(")"):
            bound = bound[1:-1]
        bound = bound.replace("-", ".")

        try:
            requirement = Requirement(name[: name_match.end()] + bound)
        except InvalidRequirement:
            return None

        if requirement.url or requirement.marker:
            return None

        new_name = canonicalize_name(requirement.name)
        if requirement.extras:
            new_name += f"[{','.join(sorted(requirement.extras))}]"

    specification = _repair_specification(",".join(part for part in (bound, specification) if part))

    if not _specification_is_valid(specification):
        return None

    if library.get("is_custom") and "[" in new_name:
        return None

    version = _pin_within(library.get("version"), specification)
    return {**library, "name": new_name, "specification": specification, "version": version}


def _repair_specification(value: str) -> str:
    """The specification with what this release refuses, but uv read the same way,
    rewritten, so a venv that built keeps building.

    Empty clauses go (packaging skipped them, uv took a trailing comma); `===` before a
    plain version becomes `==`, which admits exactly that version; whitespace other than
    a space becomes a space. A line break is left as it is, and the entry is dropped:
    in a requirement line it starts a line of its own, which is what this release
    closes. Anything still refused after the repair is refused as before.
    """
    if any(character in _LINE_BREAKS for character in value):
        return value
    value = "".join(" " if character.isspace() else character for character in value)
    clauses = []
    for clause in value.split(","):
        if not clause.strip():
            continue
        operand = clause.strip().removeprefix("===")
        if operand != clause.strip() and _VERSION_RE.fullmatch(operand.strip()):
            clause = clause.replace("===", "==", 1)
        clauses.append(clause)
    return ",".join(clauses)


def _specification_is_valid(value: str) -> bool:
    """The four checks `Library` makes on a specification, frozen here, as a yes or no."""
    if any(character.isspace() and character != " " for character in value):
        return False
    try:
        specifiers = SpecifierSet(value)
    except InvalidSpecifier:
        return False
    if value.strip() and any(not clause.strip() for clause in value.split(",")):
        return False
    return all(specifier.operator != "===" for specifier in specifiers)
