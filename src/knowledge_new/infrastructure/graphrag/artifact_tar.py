import tarfile
from collections.abc import AsyncIterator
from pathlib import PurePosixPath

from application.ports.artifact_store import AbstractArtifactStore, StoredObject
from domain.errors import ArtifactStorageError, InvalidArtifactArchiveError

_ALLOWED_TOP_FOLDERS = frozenset({"input", "lancedb", "output"})
_REQUIRED_MEMBERS = frozenset({"output/documents.parquet", "output/text_units.parquet"})
_MAX_MEMBERS = 50_000
_MAX_TOTAL_SIZE = 4 * 1024**3  # 4 GiB
# stream_tar writes a pax header only for a long or non-ASCII name: a few hundred bytes.
_MAX_EXTENDED_HEADER_SIZE = 8 * 1024
_MAX_NAME_LENGTH = 4 * 1024
# Header blocks tarfile reads into memory whole, before the member they describe.
_EXTENDED_HEADER_TYPES = frozenset(
    {tarfile.XHDTYPE, tarfile.SOLARIS_XHDTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK}
)


class _BoundedTarInfo(tarfile.TarInfo):
    """A TarInfo that refuses oversized and sparse headers before tarfile reads them.

    tarfile loads an extended header (pax, GNU long name) whole, and walks a sparse
    map entry by entry, before `read_members` ever sees the member. Their size is
    chosen by whoever wrote the tar, so it is checked here, in `_proc_member`: the
    hook tarfile's own comments name for subclasses.
    """

    def _proc_member(self, tarfile_: tarfile.TarFile):
        if self.type == tarfile.GNUTYPE_SPARSE:
            raise InvalidArtifactArchiveError(reason="tar holds a sparse member")
        # stream_tar never writes a global header, and each one is copied into every later member.
        if self.type == tarfile.XGLTYPE:
            raise InvalidArtifactArchiveError(reason="tar holds a global pax header")
        if self.type in _EXTENDED_HEADER_TYPES and self.size > _MAX_EXTENDED_HEADER_SIZE:
            raise InvalidArtifactArchiveError(
                reason=f"tar holds an extended header larger than {_MAX_EXTENDED_HEADER_SIZE} bytes"
            )
        return super()._proc_member(tarfile_)

    def _proc_gnusparse_10(self, next_member, pax_headers, tarfile_):
        # A version 1.0 sparse map sits in the data blocks, outside the bounded pax header.
        raise InvalidArtifactArchiveError(reason="tar holds a sparse member")


def open_artifact_tar(path: str) -> tarfile.TarFile:
    """Open an uncompressed GraphRAG artifact tar for `read_members`.

    Raises:
        InvalidArtifactArchiveError: The first member has an oversized or sparse header.
        tarfile.TarError: The file is not a readable tar.
    """
    return tarfile.open(path, mode="r:", tarinfo=_BoundedTarInfo)


async def stream_tar(
    store: AbstractArtifactStore, members: list[tuple[str, StoredObject]]
) -> AsyncIterator[bytes]:
    """Yield an uncompressed PAX tar of `members`, read from `store` as it is written.

    Nothing is buffered beyond one chunk of one object: each tar header is written
    from the size the listing reported, then the object's bytes are streamed after it.

    Args:
        store: Where the objects are read from.
        members: Pairs of the member's name inside the tar, relative to the slot
            (`output/entities.parquet`), and the stored object to read for it. The
            caller chooses what goes in and how it is named.

    Raises:
        ArtifactStorageError: If an object holds more or fewer bytes than its listed
            size, for example because an indexing run replaced it after the listing.
            The header already promised that size, so the tar would be corrupt.
    """
    for member_name, stored in members:
        info = tarfile.TarInfo(name=member_name)
        info.size = stored.size
        info.mode = 0o644
        yield info.tobuf(format=tarfile.PAX_FORMAT)
        written = 0
        async for chunk in store.iter_object(stored.key):
            written += len(chunk)
            yield chunk
        if written != stored.size:
            raise ArtifactStorageError(
                f"Object {stored.key} size mismatch: expected {stored.size}, got {written}"
            )
        yield b"\0" * ((-stored.size) % 512)
    yield b"\0" * 1024


def read_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    """Return the members of a GraphRAG artifact tar once every one of them is safe to restore.

    Every member is checked before any is returned, so a restore writes nothing when
    a single member is refused. A member is accepted only when it is a regular file
    whose name is a plain relative path (no `..`, no backslash, no `./` or `//`) under
    one of the slot's folders (`input/`, `output/`, `lancedb/`), and no other member
    has the same name. Sparse members, and names or pax headers past a few KB, are
    refused. The tar must hold the two tables the document id rewrite reads, and stay
    within the member count and total size caps. Members are read one at a time, so
    the count cap stops the read itself.

    Args:
        tar: An open, uncompressed tar. Open it with `open_artifact_tar`, so that an
            oversized header is refused before tarfile loads it.

    Raises:
        InvalidArtifactArchiveError: On the first rule a member breaks, or when a
            required table is missing.
    """
    members: list[tarfile.TarInfo] = []
    seen_names: set[str] = set()
    total_size = 0
    for member in tar:
        members.append(member)
        if len(members) > _MAX_MEMBERS:
            raise InvalidArtifactArchiveError(reason=f"Too many members in tar: > {_MAX_MEMBERS}")
        if len(member.name) > _MAX_NAME_LENGTH:
            raise InvalidArtifactArchiveError(
                reason=f"Member name longer than {_MAX_NAME_LENGTH} characters"
            )
        if _pax_header_size(member) > _MAX_EXTENDED_HEADER_SIZE:
            raise InvalidArtifactArchiveError(
                reason=f"Member {member.name} has pax headers past {_MAX_EXTENDED_HEADER_SIZE} bytes"
            )
        if member.issparse():
            raise InvalidArtifactArchiveError(reason=f"Member {member.name} is sparse")
        if not member.isfile():
            raise InvalidArtifactArchiveError(reason=f"Member {member.name} is not a regular file")
        if "\\" in member.name:
            raise InvalidArtifactArchiveError(reason=f"Member {member.name} has backslash in name")
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise InvalidArtifactArchiveError(reason=f"Member {member.name} has invalid path")
        if not path.parts or str(path) != member.name:
            raise InvalidArtifactArchiveError(
                reason=f"member {member.name!r} is not a plain relative path"
            )
        if path.parts[0] not in _ALLOWED_TOP_FOLDERS:
            raise InvalidArtifactArchiveError(reason=f"Member {member.name} has invalid top folder")
        if member.name in seen_names:
            raise InvalidArtifactArchiveError(reason=f"Duplicate member name: {member.name}")
        total_size += member.size
        if total_size > _MAX_TOTAL_SIZE:
            raise InvalidArtifactArchiveError(
                reason=f"Total size of members exceeds {_MAX_TOTAL_SIZE} bytes"
            )
        seen_names.add(member.name)

    for required in _REQUIRED_MEMBERS:
        if required not in seen_names:
            raise InvalidArtifactArchiveError(reason=f"Missing required member: {required}")

    return members


def _pax_header_size(member: tarfile.TarInfo) -> int:
    return sum(len(keyword) + len(value) for keyword, value in member.pax_headers.items())
