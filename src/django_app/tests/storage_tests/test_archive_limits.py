"""ArchiveExtractionGuard bounds what one archive extraction may allocate.

FileValidator rejects a bomb up front from archive headers, which is the
effective gate for uploads. This guard is the second layer, at the point where
bytes are actually allocated: `_iter_archive_entries` buffers every member with
`zf.read()` and hands it to `upload()` one at a time, so without a running total
2000 individually-honest entries still add up to an unbounded resident set, and
any caller reaching the backend directly rather than through
StorageUploadSerializer gets no header check at all.
"""

from io import BytesIO

import pytest

from tables.services.storage_service.archive_limits import (
    ArchiveExtractionGuard,
    ArchiveLimitExceeded,
)


def guard(*, max_entries=100, max_total_bytes=10_000) -> ArchiveExtractionGuard:
    return ArchiveExtractionGuard(
        max_entries=max_entries, max_total_bytes=max_total_bytes
    )


def test_accounts_entries_up_to_the_cap():
    g = guard(max_entries=3)

    for _ in range(3):
        g.account_entry()

    assert g.entries_seen == 3


def test_rejects_entry_past_the_count_cap():
    g = guard(max_entries=3)
    for _ in range(3):
        g.account_entry()

    with pytest.raises(ArchiveLimitExceeded, match="entries"):
        g.account_entry()


def test_reads_a_member_within_the_byte_budget():
    g = guard(max_total_bytes=1_000)

    data = g.read_member(BytesIO(b"x" * 500), "a.txt")

    assert data == b"x" * 500
    assert g.bytes_read == 500


def test_rejects_a_member_past_the_byte_budget():
    g = guard(max_total_bytes=100)

    with pytest.raises(ArchiveLimitExceeded, match="bytes"):
        g.read_member(BytesIO(b"x" * 500), "big.txt")


def test_byte_budget_accumulates_across_members():
    """No single member is oversized; only their sum is."""
    g = guard(max_total_bytes=250)

    g.read_member(BytesIO(b"x" * 100), "a.txt")
    g.read_member(BytesIO(b"x" * 100), "b.txt")

    with pytest.raises(ArchiveLimitExceeded, match="bytes"):
        g.read_member(BytesIO(b"x" * 100), "c.txt")


def test_stops_reading_before_buffering_the_whole_oversized_member():
    """The point of the guard is to not allocate the bomb while rejecting it."""
    g = guard(max_total_bytes=1_000)

    with pytest.raises(ArchiveLimitExceeded):
        g.read_member(BytesIO(b"x" * 50_000_000), "bomb.bin")

    assert g.bytes_read <= 1_000 + ArchiveExtractionGuard.CHUNK_BYTES


def test_rejection_names_the_offending_member():
    g = guard(max_total_bytes=10)

    with pytest.raises(ArchiveLimitExceeded, match="bomb.bin"):
        g.read_member(BytesIO(b"x" * 500), "bomb.bin")


def test_limit_error_is_a_value_error_so_the_upload_view_returns_400():
    """storage_views.upload maps ValueError to a ValidationError response."""
    assert issubclass(ArchiveLimitExceeded, ValueError)
