import io
import tarfile

import pytest
from application.ports.artifact_store import StoredObject
from domain.errors import ArtifactStorageError, InvalidArtifactArchiveError
from infrastructure.graphrag import artifact_tar
from infrastructure.graphrag.artifact_tar import read_members, stream_tar
from tests.fakes.artifact_store import InMemoryArtifactStore


SLOT_PREFIX = "graphrag/rag_7/a/"


async def _export(objects: dict[str, bytes]) -> bytes:
    """Stream every object of the slot into a tar, named relative to the slot."""
    store = InMemoryArtifactStore(objects)
    members = [
        (stored.key.removeprefix(SLOT_PREFIX), stored)
        for stored in await store.list_objects(SLOT_PREFIX)
    ]
    return b"".join([chunk async for chunk in stream_tar(store, members)])


def _read_back(archive: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        return {member.name: tar.extractfile(member).read() for member in tar.getmembers()}


async def test_tar_reads_back_with_names_relative_to_the_slot_and_the_same_bytes():
    archive = await _export(
        {
            f"{SLOT_PREFIX}output/entities.parquet": b"entities-bytes",
            f"{SLOT_PREFIX}lancedb/text_unit_text.lance/data/0001.lance": b"\x00\x01vectors",
        }
    )

    assert _read_back(archive) == {
        "output/entities.parquet": b"entities-bytes",
        "lancedb/text_unit_text.lance/data/0001.lance": b"\x00\x01vectors",
    }


async def test_tar_keeps_member_names_beyond_the_ustar_limit():
    # USTAR holds at most 256 characters (a 155 prefix plus a 100 name); PAX has no limit.
    long_name = "lancedb/community_full_content.lance/" + "_nested/" * 30 + "auxiliary.idx"
    assert len(long_name) > 256

    archive = await _export({f"{SLOT_PREFIX}{long_name}": b"index"})

    assert _read_back(archive) == {long_name: b"index"}


@pytest.mark.parametrize("size", [0, 1, 511, 512, 513, 1024 + 5])
async def test_tar_is_valid_for_sizes_around_the_512_byte_block(size):
    data = bytes(index % 251 for index in range(size))

    archive = await _export({f"{SLOT_PREFIX}output/file.bin": data})

    assert len(archive) % 512 == 0
    assert _read_back(archive) == {"output/file.bin": data}


async def test_empty_slot_gives_an_empty_but_valid_tar():
    archive = await _export({})

    assert _read_back(archive) == {}


async def test_raises_when_an_object_is_not_the_size_listed():
    store = InMemoryArtifactStore({f"{SLOT_PREFIX}output/entities.parquet": b"grew after listing"})
    listed_before_it_changed = StoredObject(key=f"{SLOT_PREFIX}output/entities.parquet", size=4)

    with pytest.raises(ArtifactStorageError):
        async for _ in stream_tar(store, [("output/entities.parquet", listed_before_it_changed)]):
            pass


# --- read_members -------------------------------------------------------------

REQUIRED_TABLES = {
    "output/documents.parquet": b"documents",
    "output/text_units.parquet": b"text units",
}


def _tar_with(members: list[tarfile.TarInfo | tuple[str, bytes]]) -> bytes:
    """Build a tar from (name, data) pairs, or from TarInfo entries for non-file members."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for member in members:
            if isinstance(member, tarfile.TarInfo):
                tar.addfile(member)
                continue
            name, data = member
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _valid_members(*extra: tarfile.TarInfo | tuple[str, bytes]):
    return [*REQUIRED_TABLES.items(), *extra]


def _read_members_of(archive: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        return [member.name for member in read_members(tar)]


def _link(name: str, target: str, link_type: bytes) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.type = link_type
    info.linkname = target
    return info


def _directory(name: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.DIRTYPE
    return info


async def test_accepts_the_tar_that_stream_tar_produces():
    archive = await _export(
        {
            f"{SLOT_PREFIX}output/documents.parquet": b"documents",
            f"{SLOT_PREFIX}output/text_units.parquet": b"text units",
            f"{SLOT_PREFIX}lancedb/entity_description.lance/data/0001.lance": b"vectors",
        }
    )

    assert sorted(_read_members_of(archive)) == [
        "lancedb/entity_description.lance/data/0001.lance",
        "output/documents.parquet",
        "output/text_units.parquet",
    ]


def test_accepts_files_in_every_slot_folder():
    archive = _tar_with(
        _valid_members(("input/raw.txt", b"raw"), ("lancedb/__manifest/a.txn", b"manifest"))
    )

    assert len(_read_members_of(archive)) == 4


@pytest.mark.parametrize(
    "bad_member",
    [
        pytest.param(_link("output/link", "/etc/passwd", tarfile.SYMTYPE), id="symlink"),
        pytest.param(
            _link("output/hard", "output/documents.parquet", tarfile.LNKTYPE), id="hard link"
        ),
        pytest.param(_directory("output/folder"), id="directory"),
        pytest.param(("/output/absolute.parquet", b"x"), id="absolute path"),
        pytest.param(("../output/escape.parquet", b"x"), id="parent at the start"),
        pytest.param(("output/../../escape.parquet", b"x"), id="parent in the middle"),
        pytest.param((r"output\..\escape.parquet", b"x"), id="backslash"),
        pytest.param(("./output/dotted.parquet", b"x"), id="leading dot segment"),
        pytest.param(("output//double.parquet", b"x"), id="double slash"),
        pytest.param(("update_output/delta.parquet", b"x"), id="folder outside the slot"),
        pytest.param(("stray.parquet", b"x"), id="file at the top level"),
        pytest.param(("output/documents.parquet", b"second copy"), id="duplicate name"),
    ],
)
def test_refuses_an_unsafe_member(bad_member):
    archive = _tar_with(_valid_members(bad_member))

    with pytest.raises(InvalidArtifactArchiveError):
        _read_members_of(archive)


@pytest.mark.parametrize("missing", sorted(REQUIRED_TABLES))
def test_refuses_a_tar_without_a_table_the_rewrite_needs(missing):
    members = [(name, data) for name, data in REQUIRED_TABLES.items() if name != missing]
    archive = _tar_with([*members, ("output/entities.parquet", b"entities")])

    with pytest.raises(InvalidArtifactArchiveError):
        _read_members_of(archive)


def test_refuses_an_empty_tar():
    with pytest.raises(InvalidArtifactArchiveError):
        _read_members_of(_tar_with([]))


def test_member_count_cap_allows_the_limit_and_refuses_one_more(monkeypatch):
    monkeypatch.setattr(artifact_tar, "_MAX_MEMBERS", 3)

    assert len(_read_members_of(_tar_with(_valid_members(("output/third.parquet", b"x"))))) == 3
    with pytest.raises(InvalidArtifactArchiveError):
        _read_members_of(
            _tar_with(_valid_members(("output/third.parquet", b"x"), ("output/fourth", b"x")))
        )


def test_total_size_cap_allows_the_limit_and_refuses_one_byte_more(monkeypatch):
    required_size = sum(len(data) for data in REQUIRED_TABLES.values())
    monkeypatch.setattr(artifact_tar, "_MAX_TOTAL_SIZE", required_size + 10)

    assert len(_read_members_of(_tar_with(_valid_members(("output/extra", b"x" * 10))))) == 3
    with pytest.raises(InvalidArtifactArchiveError):
        _read_members_of(_tar_with(_valid_members(("output/extra", b"x" * 11))))


# --- crafted tars are refused before their headers are read --------------------------------


# Every restorable index holds these; a crafted tar carries them so that only the
# crafted member can be the reason it is refused.
REQUIRED_MEMBERS = ("output/documents.parquet", "output/text_units.parquet")


def _crafted_tar(tmp_path, build) -> str:
    path = tmp_path / "crafted.tar"
    with tarfile.open(path, mode="w", **build.get("open", {})) as tar:
        for name in REQUIRED_MEMBERS:
            info, data = _member(name)
            tar.addfile(info, io.BytesIO(data))
        for info, data in build["members"]:
            tar.addfile(info, io.BytesIO(data))
    return str(path)


def _member(name: str, data: bytes = b"x", **attributes) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    for key, value in attributes.items():
        setattr(info, key, value)
    return info, data


def _read(path: str) -> list[str]:
    with artifact_tar.open_artifact_tar(path) as tar:
        return [member.name for member in read_members(tar)]


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(
            {
                "open": {"format": tarfile.PAX_FORMAT},
                "members": [_member("output/a.parquet", pax_headers={"comment": "x" * 9000})],
            },
            id="pax header past the limit",
        ),
        pytest.param(
            {
                "open": {"format": tarfile.GNU_FORMAT},
                "members": [_member("output/" + "n" * 9000 + ".parquet")],
            },
            id="GNU long name past the limit",
        ),
        pytest.param(
            {
                "open": {"format": tarfile.PAX_FORMAT, "pax_headers": {"comment": "global"}},
                "members": [_member("output/a.parquet")],
            },
            id="global pax header",
        ),
        pytest.param(
            {
                "open": {"format": tarfile.PAX_FORMAT},
                "members": [_member("output/" + "n" * 5000 + ".parquet")],
            },
            id="name longer than the limit",
        ),
        pytest.param(
            {
                "open": {"format": tarfile.GNU_FORMAT},
                "members": [_member("output/a.parquet", type=tarfile.GNUTYPE_SPARSE)],
            },
            id="sparse member",
        ),
    ],
)
def test_a_crafted_tar_is_refused(tmp_path, build):
    path = _crafted_tar(tmp_path, build)

    with pytest.raises(InvalidArtifactArchiveError):
        _read(path)


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(
            {
                "open": {"format": tarfile.PAX_FORMAT},
                "members": [_member("output/a.parquet", pax_headers={"comment": "x" * 9000})],
            },
            id="pax header past the limit",
        ),
        pytest.param(
            {
                "open": {"format": tarfile.GNU_FORMAT},
                "members": [_member("output/" + "n" * 9000 + ".parquet")],
            },
            id="GNU long name past the limit",
        ),
        pytest.param(
            {
                "open": {"format": tarfile.PAX_FORMAT, "pax_headers": {"comment": "global"}},
                "members": [_member("output/a.parquet")],
            },
            id="global pax header",
        ),
        pytest.param(
            {
                "open": {"format": tarfile.GNU_FORMAT},
                "members": [_member("output/a.parquet", type=tarfile.GNUTYPE_SPARSE)],
            },
            id="sparse member",
        ),
    ],
)
def test_an_oversized_or_unusual_header_is_refused_while_tarfile_reads_it(tmp_path, build):
    # Refused by the header hook itself, before tarfile holds the header in memory:
    # iterating alone, without read_members, already fails.
    path = _crafted_tar(tmp_path, build)

    with pytest.raises(InvalidArtifactArchiveError), artifact_tar.open_artifact_tar(path) as tar:
        for _member_info in tar:
            pass


def test_a_long_but_ordinary_name_is_accepted(tmp_path):
    long_name = "lancedb/community_full_content.lance/" + "_nested/" * 30 + "auxiliary.idx"
    path = _crafted_tar(
        tmp_path, {"open": {"format": tarfile.PAX_FORMAT}, "members": [_member(long_name)]}
    )

    assert _read(path) == [*REQUIRED_MEMBERS, long_name]


@pytest.mark.parametrize(("count", "refused"), [(1, False), (2, True)])
def test_member_count_is_checked_while_reading(tmp_path, monkeypatch, count, refused):
    # The limit counts the required members too: 2 of them plus `count` more.
    monkeypatch.setattr(artifact_tar, "_MAX_MEMBERS", 3)
    path = _crafted_tar(
        tmp_path,
        {"members": [_member(f"output/file_{index}.parquet") for index in range(count)]},
    )

    if refused:
        with pytest.raises(InvalidArtifactArchiveError):
            _read(path)
    else:
        assert len(_read(path)) == len(REQUIRED_MEMBERS) + count
