"""Test venv cache hash calculation with content-awareness for local path dependencies.

This module verifies that _fingerprint_library correctly:
- Hashes content changes in local directories
- Ignores excluded artifacts (.venv, __pycache__, etc.)
- Passes through plain pip specifications unchanged
- Changes hash when local path content changes
"""

import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import dynamic_venv_executor_chain
from dynamic_venv_executor_chain import (
    CreateVenvHandler,
    InstallLibrariesHandler,
    _fingerprint_library,
)


def test_fingerprint_library_with_plain_pip_spec():
    """Plain pip specs (non-local paths) pass through unchanged."""
    spec = "requests==2.28.0"
    assert _fingerprint_library(spec) == spec

    spec_with_extras = "numpy>=1.20.0"
    assert _fingerprint_library(spec_with_extras) == spec_with_extras


def test_fingerprint_library_with_nonexistent_path():
    """Nonexistent local paths pass through unchanged (not directories)."""
    path = "/nonexistent/path/to/lib"
    assert _fingerprint_library(path) == path


def test_fingerprint_library_with_local_directory(tmp_path):
    """Local directory gets content-hashed (sha256 of relative path + file content)."""
    lib_dir = tmp_path / "test_lib"
    lib_dir.mkdir()

    # Create some files
    (lib_dir / "module.py").write_text("def hello(): pass")
    (lib_dir / "data.json").write_text('{"key": "value"}')

    # Get the fingerprint
    fingerprint1 = _fingerprint_library(str(lib_dir))

    # Fingerprint should be a hex string (sha256 output)
    assert len(fingerprint1) == 64  # sha256 hex digest is 64 chars
    assert all(c in "0123456789abcdef" for c in fingerprint1)

    # Change file content and verify hash changes
    (lib_dir / "module.py").write_text("def hello(): pass MODIFIED")
    fingerprint2 = _fingerprint_library(str(lib_dir))
    assert fingerprint2 != fingerprint1


def test_fingerprint_library_stable_with_excluded_artifacts(tmp_path):
    """Hash stays stable when only excluded artifacts change."""
    lib_dir = tmp_path / "test_lib"
    lib_dir.mkdir()

    # Create main files
    (lib_dir / "module.py").write_text("def hello(): pass")

    # Get the baseline fingerprint
    fingerprint1 = _fingerprint_library(str(lib_dir))

    # Add excluded directories/files
    venv_dir = lib_dir / ".venv"
    venv_dir.mkdir()
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/local/bin")

    pycache_dir = lib_dir / "__pycache__"
    pycache_dir.mkdir()
    (pycache_dir / "module.cpython-312.pyc").write_bytes(b"fake bytecode")

    pytest_dir = lib_dir / ".pytest_cache"
    pytest_dir.mkdir()
    (pytest_dir / "last_run.json").write_text('{}')

    git_dir = lib_dir / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("")

    egg_info = lib_dir / "test_lib.egg-info"
    egg_info.mkdir()
    (egg_info / "PKG-INFO").write_text("Name: test-lib")

    # Fingerprint should remain unchanged
    fingerprint2 = _fingerprint_library(str(lib_dir))
    assert fingerprint2 == fingerprint1


def test_fingerprint_library_stable_when_content_unchanged(tmp_path):
    """Hash stays stable across repeated calls when content doesn't change."""
    lib_dir = tmp_path / "test_lib"
    lib_dir.mkdir()

    # Create files with specific content
    (lib_dir / "a.py").write_text("content_a")
    (lib_dir / "b.py").write_text("content_b")
    subdir = lib_dir / "subdir"
    subdir.mkdir()
    (subdir / "c.py").write_text("content_c")

    # Call multiple times
    fp1 = _fingerprint_library(str(lib_dir))
    fp2 = _fingerprint_library(str(lib_dir))
    fp3 = _fingerprint_library(str(lib_dir))

    assert fp1 == fp2 == fp3


def test_create_venv_handler_calculate_hash_with_mixed_libraries(tmp_path):
    """CreateVenvHandler.calculate_hash combines fingerprints of mixed library types."""
    lib_dir = tmp_path / "my_lib"
    lib_dir.mkdir()
    (lib_dir / "module.py").write_text("def foo(): pass")

    handler = CreateVenvHandler()

    # Mix of local paths and pip specs
    libraries = [
        str(lib_dir),
        "requests==2.28.0",
        "numpy>=1.20.0",
    ]

    hash1 = handler.calculate_hash(libraries)

    # Verify it's a sha256 hex digest
    assert len(hash1) == 64
    assert all(c in "0123456789abcdef" for c in hash1)

    # Modify the local lib content
    (lib_dir / "module.py").write_text("def foo(): pass # modified")
    hash2 = handler.calculate_hash(libraries)

    # Hash should change because local lib content changed
    assert hash2 != hash1

    # Modify a pip spec (not the local lib)
    libraries_modified = [
        str(lib_dir),
        "requests==2.29.0",  # version changed
        "numpy>=1.20.0",
    ]
    hash3 = handler.calculate_hash(libraries_modified)

    # Hash should change because pip spec changed
    assert hash3 != hash1


def test_install_libraries_handler_calculate_hash_consistency(tmp_path):
    """InstallLibrariesHandler.calculate_hash is consistent with CreateVenvHandler."""
    lib_dir = tmp_path / "my_lib"
    lib_dir.mkdir()
    (lib_dir / "module.py").write_text("def bar(): pass")

    create_handler = CreateVenvHandler()
    install_handler = InstallLibrariesHandler()

    libraries = [str(lib_dir), "pytest>=7.0"]

    # Both handlers should produce the same hash
    hash_create = create_handler.calculate_hash(libraries)
    hash_install = install_handler.calculate_hash(libraries)

    assert hash_create == hash_install

    # When local lib changes, both should reflect it
    (lib_dir / "module.py").write_text("def bar(): pass # modified")

    hash_create_after = create_handler.calculate_hash(libraries)
    hash_install_after = install_handler.calculate_hash(libraries)

    assert hash_create_after == hash_install_after
    assert hash_create_after != hash_create


def test_fingerprint_library_handles_unreadable_file(tmp_path, monkeypatch):
    """_fingerprint_library skips unreadable files with a warning and continues hashing."""
    lib_dir = tmp_path / "test_lib"
    lib_dir.mkdir()

    # Create multiple files
    readable_file_1 = lib_dir / "readable1.py"
    readable_file_1.write_text("def func1(): pass")

    unreadable_file = lib_dir / "unreadable.py"
    unreadable_file.write_text("should not be read")

    readable_file_2 = lib_dir / "readable2.py"
    readable_file_2.write_text("def func2(): pass")

    # Monkeypatch Path.read_bytes to raise OSError for the unreadable file
    original_read_bytes = Path.read_bytes

    def mock_read_bytes(self):
        if self == unreadable_file:
            raise OSError("Permission denied")
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", mock_read_bytes)

    # Fingerprint should succeed (not raise), skipping the unreadable file
    fingerprint = _fingerprint_library(str(lib_dir))

    # Should be a valid 64-char hex digest
    assert len(fingerprint) == 64
    assert all(c in "0123456789abcdef" for c in fingerprint)

    # Verify the hash reflects readable files only
    # Get a baseline without the unreadable file to compare
    lib_dir_readable_only = tmp_path / "test_lib_readable"
    lib_dir_readable_only.mkdir()
    (lib_dir_readable_only / "readable1.py").write_text("def func1(): pass")
    (lib_dir_readable_only / "readable2.py").write_text("def func2(): pass")

    # Reset monkeypatch to get true behavior
    monkeypatch.undo()

    fingerprint_readable_only = _fingerprint_library(str(lib_dir_readable_only))

    # The hashes should match (same files hashed)
    assert fingerprint == fingerprint_readable_only
