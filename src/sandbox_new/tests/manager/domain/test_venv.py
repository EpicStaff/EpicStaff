"""Behavior of the manager's domain models."""

import pytest
from pydantic import ValidationError

from manager.domain.enums import VenvStatus
from manager.domain.models import Library, Venv
from tests.builders import make_library, make_venv


@pytest.mark.parametrize("specification", ["", ">=2.0", ">=1.0,<2", "==1.2.3", "~=1.4"])
def test_library_accepts_valid_version_specifications(specification):
    assert make_library(specification=specification).specification == specification


@pytest.mark.parametrize("specification", ["=>2.0", "2.0", ">>1.0"])
def test_library_rejects_invalid_version_specifications(specification):
    with pytest.raises(ValidationError):
        make_library(specification=specification)


@pytest.mark.parametrize("version", ["1.2.3", "1", "2!1.0rc1.post1.dev2", "1.0b2"])
def test_library_accepts_valid_versions(version):
    assert make_library(version=version).version == version


@pytest.mark.parametrize("version", ["01.2", "v1.2", "1.2.3.", "latest"])
def test_library_rejects_invalid_versions(version):
    with pytest.raises(ValidationError):
        make_library(version=version)


def test_library_rejects_an_empty_name():
    with pytest.raises(ValidationError):
        Library(name="")


def test_venv_rename_changes_the_name():
    venv = make_venv(name="old")
    venv.rename("new")
    assert venv.name == "new"


def test_venv_set_libs_returns_the_venv_to_declared_and_clears_the_error():
    venv = make_venv(status=VenvStatus.FAILED, error="uv blew up")
    libs = [make_library(name="pandas")]

    venv.set_libs(libs)

    assert venv.libs == libs
    assert venv.status is VenvStatus.DECLARED
    assert venv.error is None


def test_venv_mark_as_processing_keeps_a_previous_error():
    venv = make_venv(status=VenvStatus.FAILED, error="uv blew up")
    venv.mark_as_processing()
    assert venv.status is VenvStatus.PROCESSING
    assert venv.error == "uv blew up"


def test_venv_mark_as_completed_clears_the_error():
    venv = make_venv(status=VenvStatus.PROCESSING, error="stale")
    venv.mark_as_completed()
    assert venv.status is VenvStatus.COMPLETED
    assert venv.error is None


def test_venv_mark_as_failed_records_the_exception_text():
    venv = make_venv(status=VenvStatus.PROCESSING)
    venv.mark_as_failed(RuntimeError("uv pip sync failed"))
    assert venv.status is VenvStatus.FAILED
    assert venv.error == "uv pip sync failed"


def test_venv_id_cannot_be_reassigned():
    venv = Venv(id=1, name="default")
    with pytest.raises(ValidationError):
        venv.id = 2
