import sys
from pathlib import Path

import pytest

from es_plugins.packages.wheel_tag_check import (
    IncompatibleWheelError,
    check_wheel_tags,
    incompatible_projects,
    supported_tags,
)
from tests.helpers import FOREIGN_WHEEL_TAG, make_wheel

INTERPRETER = Path(sys.executable)


def test_a_project_with_a_wheel_for_another_platform_only_is_named():
    problems = incompatible_projects(
        [f"pydantic_core-2.46.4-{FOREIGN_WHEEL_TAG}.whl", "fastapi-0.141.1-py3-none-any.whl"],
        ["cp313-cp313-manylinux_2_36_aarch64", "py3-none-any"],
    )

    assert problems == [
        f"pydantic-core 2.46.4 has no wheel for this node (its wheels are built for {FOREIGN_WHEEL_TAG})"
    ]


def test_a_project_with_wheels_for_both_architectures_passes_on_either():
    # A universal lock ships one wheel per platform; the project installs on the node whose tag
    # one of them matches, and the other-architecture wheel next to it is not a problem.
    wheels = [
        "pydantic_core-2.46.4-cp313-cp313-manylinux_2_28_x86_64.whl",
        "pydantic_core-2.46.4-cp313-cp313-manylinux_2_28_aarch64.whl",
    ]
    assert incompatible_projects(wheels, ["cp313-cp313-manylinux_2_28_aarch64"]) == []
    assert incompatible_projects(wheels, ["cp313-cp313-manylinux_2_28_x86_64"]) == []


def test_a_compressed_tag_set_fits_when_one_of_its_tags_does():
    wheel = "pydantic_core-2.46.4-cp313-cp313-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"

    assert incompatible_projects([wheel], ["cp313-cp313-manylinux2014_aarch64"]) == []


def test_a_file_that_is_not_a_wheel_name_is_reported():
    assert incompatible_projects(["notes.whl"], ["py3-none-any"]) == [
        "notes.whl is not a valid wheel file name"
    ]


async def test_the_interpreter_lists_its_own_tags_most_specific_first():
    tags = await supported_tags(INTERPRETER)

    major, minor = sys.version_info[:2]
    assert tags[0].startswith(f"cp{major}{minor}-cp{major}{minor}")
    assert "py3-none-any" in tags


async def test_wheels_the_interpreter_can_install_pass(tmp_path):
    make_wheel(tmp_path, "uvicorn", "0.52.3")

    await check_wheel_tags(INTERPRETER, tmp_path)


async def test_a_project_with_no_compatible_wheel_is_refused_naming_it_and_the_node(tmp_path):
    make_wheel(tmp_path, "uvicorn", "0.52.3")
    make_wheel(tmp_path, "pydantic-core", "2.46.4", tag=FOREIGN_WHEEL_TAG)

    with pytest.raises(IncompatibleWheelError) as refused:
        await check_wheel_tags(INTERPRETER, tmp_path)

    message = str(refused.value)
    assert f"pydantic-core 2.46.4 has no wheel for this node (its wheels are built for {FOREIGN_WHEEL_TAG})" in message
    major, minor = sys.version_info[:2]
    assert f"this node is cp{major}{minor}-cp{major}{minor}" in message
    assert "uvicorn" not in message


async def test_a_project_passes_when_one_of_its_wheels_fits_this_node(tmp_path):
    # Both architectures shipped, as `pack --download-wheels` writes by default; the node's own
    # wheel is accepted and the other-architecture one does not fail the check.
    make_wheel(tmp_path, "uvicorn", "0.52.3")
    make_wheel(tmp_path, "pydantic-core", "2.46.4", tag=FOREIGN_WHEEL_TAG)
    major, minor = sys.version_info[:2]
    native = (await supported_tags(INTERPRETER))[0]
    make_wheel(tmp_path, "pydantic-core", "2.46.4", tag=native)

    await check_wheel_tags(INTERPRETER, tmp_path)


async def test_a_backend_without_wheels_needs_no_interpreter(tmp_path):
    await check_wheel_tags(tmp_path / "no-such-python", tmp_path / "wheels")


async def test_an_interpreter_that_hangs_is_stopped(tmp_path, monkeypatch):
    from es_plugins.packages import wheel_tag_check

    monkeypatch.setattr(wheel_tag_check, "_PROBE_TIMEOUT_SECONDS", 0.3)
    hanging = tmp_path / "python3.13"
    hanging.write_text("#!/bin/sh\nexec sleep 30\n")
    hanging.chmod(0o755)

    with pytest.raises(IncompatibleWheelError, match="did not list its wheel tags in time"):
        await supported_tags(hanging)
