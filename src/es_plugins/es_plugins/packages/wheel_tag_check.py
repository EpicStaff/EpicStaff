"""Refuse a package no wheel of which the plugin's interpreter can install, before pip runs.

pip only says "Could not find a version that satisfies the requirement" for a project built
for another platform. Here the wheels are grouped by project and version and each group's
tags are compared with the tags the plugin's own interpreter supports
(`packaging.tags.sys_tags()` run by that interpreter, so its version, ABI, architecture and
glibc count). A universal lock ships one wheel per platform for a compiled project, so a
project is a problem only when **none** of its wheels fits; the message names the platforms
its wheels are built for and the node's own tag.
"""

import asyncio
import json
from pathlib import Path

import packaging
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

_SUPPORTED_TAGS_PROGRAM = """
import json, sys
sys.path.append(sys.argv[1])
from packaging.tags import sys_tags
print(json.dumps([str(tag) for tag in sys_tags()]))
"""
_PROBE_TIMEOUT_SECONDS = 60
_WHEELS_NAMED = 3


class IncompatibleWheelError(Exception):
    """A wheel cannot be installed by the plugin's interpreter; the message names it."""


async def supported_tags(interpreter: Path) -> list[str]:
    """The tags `interpreter` installs, most specific first.

    The interpreter runs isolated (`-I`) with only this agent's copy of `packaging` (pure
    Python) appended to its path, so nothing of the plugin is imported.
    """
    packaging_parent = str(Path(packaging.__file__).resolve().parent.parent)
    process = await asyncio.create_subprocess_exec(
        str(interpreter),
        "-I",
        "-c",
        _SUPPORTED_TAGS_PROGRAM,
        packaging_parent,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={"LANG": "C.UTF-8"},
    )
    try:
        output, errors = await asyncio.wait_for(process.communicate(), _PROBE_TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise IncompatibleWheelError(f"{interpreter} did not list its wheel tags in time") from None
    if process.returncode != 0:
        raise IncompatibleWheelError(
            f"{interpreter} could not list its wheel tags: {errors.decode(errors='replace')[-500:]}"
        )
    return json.loads(output)


def incompatible_projects(wheel_names: list[str], tags: list[str]) -> list[str]:
    """Describe each project no wheel of which the interpreter supports.

    Wheels are grouped by (project, version). A project with at least one wheel whose tags
    the interpreter supports is fine, whatever other-platform wheels sit next to it. A group
    with no compatible wheel is described as "project version has no wheel for this node (its
    wheels are built for …)". An unparseable file name is its own problem.
    """
    supported = set(tags)
    groups: dict[tuple[str, str], dict] = {}
    problems = []
    for name in sorted(wheel_names):
        try:
            project, version, _, wheel_tags = parse_wheel_filename(name)
        except InvalidWheelFilename:
            problems.append(f"{name} is not a valid wheel file name")
            continue
        group = groups.setdefault(
            (str(project), str(version)), {"compatible": False, "built_for": set()}
        )
        if any(str(tag) in supported for tag in wheel_tags):
            group["compatible"] = True
        group["built_for"].update(str(tag) for tag in wheel_tags)
    for (project, version), group in sorted(groups.items()):
        if not group["compatible"]:
            built_for = ", ".join(sorted(group["built_for"]))
            problems.append(
                f"{project} {version} has no wheel for this node (its wheels are built for {built_for})"
            )
    return problems


async def check_wheel_tags(interpreter: Path, wheels_directory: Path) -> None:
    """Raise unless every project in `wheels_directory` has a wheel `interpreter` can install.

    Raises:
        IncompatibleWheelError: A project has no compatible wheel; the message names up to
            three such projects and the node's own most specific tag.
    """
    wheel_names = (
        [path.name for path in wheels_directory.glob("*.whl")] if wheels_directory.is_dir() else []
    )
    if not wheel_names:
        return
    tags = await supported_tags(interpreter)
    problems = incompatible_projects(wheel_names, tags)
    if problems:
        node = tags[0] if tags else "unknown"
        more = (
            f" (and {len(problems) - _WHEELS_NAMED} more)" if len(problems) > _WHEELS_NAMED else ""
        )
        raise IncompatibleWheelError(
            f"{'; '.join(problems[:_WHEELS_NAMED])}{more}; this node is {node}"
        )
