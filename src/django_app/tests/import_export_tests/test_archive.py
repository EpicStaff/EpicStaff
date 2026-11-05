"""Export archives: what the writer produces and which uploads the reader refuses."""

import io
import json
import os
import zipfile

import pytest

from tables.import_export.archive import (
    ENVELOPE_MEMBER,
    ArchiveMemberMissingError,
    ExportArchiveWriter,
    ImportArchive,
    InvalidArchiveError,
    detect_file_kind,
)
from tables.services.storage_service.archive_unpacking.extraction_guard import (
    ArchiveLimitExceeded,
)

MAX_ENTRIES = 5
MAX_UNCOMPRESSED_SIZE = 10_000


@pytest.fixture(autouse=True)
def archive_limits(settings):
    settings.MAX_KNOWLEDGE_ARCHIVE_ENTRIES = MAX_ENTRIES
    settings.MAX_KNOWLEDGE_ARCHIVE_UNCOMPRESSED_SIZE = MAX_UNCOMPRESSED_SIZE


def _zip(tmp_path, members: dict[str, bytes | str], *, extra: list[zipfile.ZipInfo] = ()) -> str:
    path = tmp_path / "upload.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
        for info in extra:
            archive.writestr(info, b"x")
    return str(path)


def _member_with_mode(name: str, file_mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.external_attr = file_mode << 16
    return info


# --- detect_file_kind -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("head", "kind"),
    [
        (b"PK\x03\x04rest", "zip"),
        (b'{"version": 5}', "json"),
        (b"", "json"),
        (b"PK", "json"),
    ],
)
def test_detect_file_kind(head, kind):
    assert detect_file_kind(head) == kind


# --- writer -> reader --------------------------------------------------------------------


def test_round_trip_keeps_the_envelope_and_every_member_byte_for_byte(settings):
    settings.MAX_KNOWLEDGE_ARCHIVE_UNCOMPRESSED_SIZE = 10 * 1024 * 1024
    # Bigger than one copy chunk, so add_file streams it in pieces.
    large = os.urandom(3 * 1024 * 1024)
    with ExportArchiveWriter() as writer:
        writer.write_envelope({"version": 6, "main_entity": "SourceCollection"})
        writer.add_bytes("knowledge/documents/1", b"document")
        writer.add_file("knowledge/graph/2.tar", io.BytesIO(large))

    try:
        with ImportArchive.open(writer.path) as archive:
            assert archive.envelope() == {"version": 6, "main_entity": "SourceCollection"}
            with archive.open_member("knowledge/documents/1") as member:
                assert member.read() == b"document"
            with archive.open_member("knowledge/graph/2.tar") as member:
                assert member.read() == large
    finally:
        os.unlink(writer.path)


def test_a_failed_export_leaves_no_temporary_file():
    with pytest.raises(RuntimeError):
        with ExportArchiveWriter() as writer:
            writer.add_bytes("knowledge/documents/1", b"document")
            raise RuntimeError("export failed")

    assert not os.path.exists(writer.path)


# --- refused uploads ----------------------------------------------------------------------


ENVELOPE = {ENVELOPE_MEMBER: "{}"}


@pytest.mark.parametrize(
    ("members", "extra"),
    [
        pytest.param({**ENVELOPE, "../outside": "x"}, [], id="parent escape"),
        pytest.param({**ENVELOPE, "knowledge/../../outside": "x"}, [], id="nested escape"),
        pytest.param({**ENVELOPE, "/etc/passwd": "x"}, [], id="absolute"),
        pytest.param({**ENVELOPE, "knowledge\\..\\..\\outside": "x"}, [], id="backslash escape"),
        pytest.param({**ENVELOPE, "knowledge/./documents/1": "x"}, [], id="dot segment"),
        pytest.param(ENVELOPE, [_member_with_mode("link", 0o120777)], id="symlink"),
        pytest.param({"knowledge/documents/1": "x"}, [], id="no export.json"),
        pytest.param(
            {**ENVELOPE, **{f"knowledge/documents/{i}": "x" for i in range(MAX_ENTRIES)}},
            [],
            id="one entry too many",
        ),
        pytest.param(
            {**ENVELOPE, "big": "x" * (MAX_UNCOMPRESSED_SIZE - 1)}, [], id="unpacks too big"
        ),
    ],
)
def test_an_unsafe_archive_is_refused_before_any_member_is_read(tmp_path, members, extra):
    path = _zip(tmp_path, members, extra=extra)

    with pytest.raises(InvalidArchiveError) as raised:
        ImportArchive.open(path)

    assert raised.value.detail["code"] == "invalid_archive"
    # Refusing closes the file again, or the import could not delete its upload.
    os.unlink(path)


def test_limits_are_inclusive(tmp_path):
    # Exactly MAX_ENTRIES entries and exactly MAX_UNCOMPRESSED_SIZE bytes are accepted.
    members = {ENVELOPE_MEMBER: "{}", "big": "x" * (MAX_UNCOMPRESSED_SIZE - 2)}
    members.update({f"small/{i}": "" for i in range(MAX_ENTRIES - 2)})

    with ImportArchive.open(_zip(tmp_path, members)) as archive:
        assert archive.envelope() == {}


def test_duplicate_member_names_are_refused(tmp_path):
    path = tmp_path / "upload.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(ENVELOPE_MEMBER, "{}")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("knowledge/documents/1", "first")
            archive.writestr("knowledge/documents/1", "second")

    with pytest.raises(InvalidArchiveError):
        ImportArchive.open(str(path))


def test_an_encrypted_member_is_refused(tmp_path):
    path = _zip(tmp_path, {ENVELOPE_MEMBER: "{}", "secret": "x"})
    # Set the "encrypted" bit in both the local header and the central directory.
    data = bytearray((tmp_path / "upload.zip").read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = 0
        while (start := data.find(signature, start)) != -1:
            data[start + flag_offset] |= 0x1
            start += 4
    (tmp_path / "upload.zip").write_bytes(bytes(data))

    with pytest.raises(InvalidArchiveError):
        ImportArchive.open(path)


@pytest.mark.parametrize(
    "content",
    [pytest.param(b"definitely not a zip", id="not a zip"), pytest.param(b"", id="empty")],
)
def test_a_file_that_is_not_a_zip_is_refused(tmp_path, content):
    path = tmp_path / "upload.zip"
    path.write_bytes(content)

    with pytest.raises(InvalidArchiveError):
        ImportArchive.open(str(path))

    path.unlink()


def test_directory_entries_are_allowed(tmp_path):
    path = _zip(tmp_path, {"knowledge/": "", ENVELOPE_MEMBER: "{}"})

    with ImportArchive.open(path) as archive:
        assert archive.envelope() == {}


# --- reading -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "envelope",
    [pytest.param(b"{not json", id="not json"), pytest.param(b"\xff\xfe", id="not utf-8")],
)
def test_an_unreadable_envelope_is_refused(tmp_path, envelope):
    with ImportArchive.open(_zip(tmp_path, {ENVELOPE_MEMBER: envelope})) as archive:
        with pytest.raises(InvalidArchiveError):
            archive.envelope()


def test_a_member_the_archive_lacks_raises_member_missing(tmp_path):
    with ImportArchive.open(_zip(tmp_path, ENVELOPE)) as archive:
        with pytest.raises(ArchiveMemberMissingError) as raised:
            archive.open_member("knowledge/documents/404")

    assert raised.value.detail["code"] == "archive_member_missing"


def test_reading_stops_once_the_whole_archive_passes_the_size_cap(tmp_path):
    # Each member fits, but reading them again and again adds up past the cap.
    members = {ENVELOPE_MEMBER: json.dumps({"padding": "x" * 4000})}
    with ImportArchive.open(_zip(tmp_path, members)) as archive:
        archive.envelope()
        archive.envelope()
        with pytest.raises(ArchiveLimitExceeded):
            archive.envelope()


# --- export.json has a cap of its own ------------------------------------------------------


@pytest.mark.parametrize(("envelope_size", "refused"), [(100, False), (101, True)])
def test_export_json_past_its_own_cap_is_refused_at_open(
    tmp_path, settings, envelope_size, refused
):
    # Well under the whole-archive cap: export.json is parsed whole, so it has its own.
    settings.MAX_EXPORT_ENVELOPE_SIZE = 100
    envelope = '{"padding": "' + "x" * (envelope_size - 15) + '"}'
    assert len(envelope) == envelope_size
    path = _zip(tmp_path, {ENVELOPE_MEMBER: envelope})

    if refused:
        with pytest.raises(InvalidArchiveError) as raised:
            ImportArchive.open(path)
        assert raised.value.detail["code"] == "invalid_archive"
    else:
        with ImportArchive.open(path) as archive:
            assert archive.envelope() == json.loads(envelope)


def test_reading_export_json_stops_at_its_cap(tmp_path, settings):
    # The cap holds while reading too, not only on the size the archive declares.
    envelope = json.dumps({"padding": "x" * 200})
    with ImportArchive.open(_zip(tmp_path, {ENVELOPE_MEMBER: envelope})) as archive:
        settings.MAX_EXPORT_ENVELOPE_SIZE = 100
        with pytest.raises(InvalidArchiveError) as raised:
            archive.envelope()

    # Refused for its size, not because the first 100 bytes are not whole JSON.
    assert "unpacks to more than 100 bytes" in str(raised.value.detail["detail"])
