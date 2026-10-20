import io
import os
import stat
import zipfile

import pytest
from plugins.packages.spa_publisher import SpaPublisher, UnsafeSpaPathError

SPA = {"spa/index.html": b"<!doctype html>", "spa/assets/app.js": b"console.log(1)", "spa/assets/img/logo.png": b"png"}


def _archive(files: dict[str, bytes]) -> zipfile.ZipFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    return zipfile.ZipFile(buffer)


@pytest.fixture
def root(tmp_path_factory):
    return tmp_path_factory.mktemp("plugin-spa")


def _write(root, version="0.1.0", files=SPA, identifier="weather"):
    with _archive(files) as archive:
        return SpaPublisher(root).write_version(identifier, version, archive, list(files))


def _publish(root, version="0.1.0", files=SPA, identifier="weather"):
    version_directory = _write(root, version, files, identifier)
    SpaPublisher(root).switch_current(identifier, version)
    return version_directory


def test_a_version_is_written_to_its_own_directory(root):
    version_directory = _write(root)

    assert version_directory == root / "weather" / "0.1.0"
    assert (version_directory / "index.html").read_bytes() == b"<!doctype html>"
    assert (version_directory / "assets" / "img" / "logo.png").read_bytes() == b"png"


def test_a_written_version_is_not_served_until_current_is_switched(root):
    _write(root)

    assert not (root / "weather" / "current").exists()


def test_current_is_a_relative_symlink_to_the_version(root):
    _publish(root)

    current = root / "weather" / "current"
    assert current.is_symlink()
    assert os.readlink(current) == "0.1.0"
    assert (current / "index.html").read_bytes() == b"<!doctype html>"


def test_current_cannot_point_at_a_version_never_written(root):
    _publish(root)

    with pytest.raises(FileNotFoundError):
        SpaPublisher(root).switch_current("weather", "9.9.9")

    assert os.readlink(root / "weather" / "current") == "0.1.0"


def test_directories_are_0755_and_files_0644_whatever_the_umask(root):
    previous = os.umask(0o077)
    try:
        version_directory = _write(root)
    finally:
        os.umask(previous)

    for directory in (root / "weather", version_directory, version_directory / "assets", version_directory / "assets" / "img"):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o755, directory
    for file in (version_directory / "index.html", version_directory / "assets" / "app.js"):
        assert stat.S_IMODE(file.stat().st_mode) == 0o644, file


def test_a_new_version_switches_current_and_leaves_nothing_behind(root):
    _publish(root, "0.1.0")

    _publish(root, "0.2.0", {"spa/index.html": b"v2"})

    plugin_directory = root / "weather"
    assert os.readlink(plugin_directory / "current") == "0.2.0"
    assert (plugin_directory / "current" / "index.html").read_bytes() == b"v2"
    assert sorted(entry.name for entry in plugin_directory.iterdir()) == ["0.1.0", "0.2.0", "current"]


def test_a_version_left_by_an_unfinished_approval_is_replaced(root):
    stale = root / "weather" / "0.1.0"
    stale.mkdir(parents=True)
    (stale / "stale.js").write_text("old")

    _write(root)

    assert not (stale / "stale.js").exists()
    assert (stale / "index.html").exists()


def test_discarding_removes_an_unserved_version_and_keeps_the_served_one(root):
    _publish(root, "0.1.0")
    _write(root, "0.2.0")
    publisher = SpaPublisher(root)

    publisher.discard_version("weather", "0.2.0")
    publisher.discard_version("weather", "0.1.0")

    assert not (root / "weather" / "0.2.0").exists()
    assert (root / "weather" / "current" / "index.html").exists()


def test_removing_a_plugin_removes_all_its_files(root):
    _publish(root)
    _publish(root, identifier="forecast")

    SpaPublisher(root).remove_plugin("weather")
    SpaPublisher(root).remove_plugin("never-published")

    assert [entry.name for entry in root.iterdir()] == ["forecast"]


@pytest.mark.parametrize(
    "path",
    ["spa/../../escape.html", "spa/../escape.html", "spa//x.html", "spa/./x.html", "other/x.html", "spa/", "/spa/x.html"],
)
def test_paths_that_would_leave_the_spa_directory_are_blocked(root, path):
    with pytest.raises(UnsafeSpaPathError):
        _write(root, files={"spa/index.html": b"ok", path: b"evil"})

    plugin_directory = root / "weather"
    assert not (plugin_directory / "0.1.0").exists()
    assert not (root / "escape.html").exists()
    assert [entry.name for entry in plugin_directory.iterdir()] == []


@pytest.mark.parametrize(("identifier", "version"), [("../etc", "0.1.0"), ("weather", "../../x"), ("weather", "1.0")])
def test_an_unsafe_identifier_or_version_is_blocked(root, identifier, version):
    publisher = SpaPublisher(root)

    with pytest.raises(UnsafeSpaPathError):
        _write(root, version=version, identifier=identifier)
    for action in (publisher.switch_current, publisher.discard_version):
        with pytest.raises(UnsafeSpaPathError):
            action(identifier, version)

    assert list(root.iterdir()) == []


def test_removing_an_unsafe_identifier_is_blocked(root):
    with pytest.raises(UnsafeSpaPathError):
        SpaPublisher(root).remove_plugin("..")
