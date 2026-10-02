"""Proves the epicstaff_common plumbing works end-to-end for tool authors."""

import tomllib
from pathlib import Path

from conftest import SHARED_DIR


def test_epicstaff_common_pyproject_is_valid_and_matches_package_dir_layout():
    pyproject_path = SHARED_DIR / "epicstaff_common" / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        pyproject = tomllib.load(f)

    assert pyproject["project"]["name"] == "epicstaff-common"
    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"
    assert pyproject["tool"]["setuptools"]["packages"] == ["epicstaff_common"]
    assert pyproject["tool"]["setuptools"]["package-dir"] == {"epicstaff_common": "."}


def test_sandbox_registers_epicstaff_common_unconditionally():
    """Assert against the real sandbox source, not a copy of the literal path,
    so this fails if the registration line is ever removed or renamed."""
    sandbox_chain_path = (
        SHARED_DIR.parent / "sandbox" / "dynamic_venv_executor_chain.py"
    )
    source = sandbox_chain_path.read_text(encoding="utf-8")

    # The line must sit in the unconditional predefined_libraries block, not
    # behind the `if context.get("use_storage")` guard that gates
    # epicstaff_storage — so check it appears before that guard.
    unconditional_block, _, rest = source.partition('if context.get("use_storage")')
    assert '"/app/src/shared/epicstaff_common"' in unconditional_block
    assert '"/app/src/shared/epicstaff_storage"' not in unconditional_block
    assert '"/app/src/shared/epicstaff_storage"' in rest
