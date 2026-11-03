"""The library keeps a run inside the organization's remaining storage when django says how much is left.

Django hands the run `STORAGE_FREE_BYTES` and `STORAGE_PURGEABLE_BYTES`. A write that fits is
untouched, one that only fits once the recycle bin is purged goes ahead after a warning on
stderr, and one that fits even then not is refused before anything is written. With the
variables absent nothing changes.
"""

import pytest

from epicstaff_storage import StorageQuotaExceededError
from fakes import FakeS3Client

WARNING = (
    "This file may not fit in the remaining storage ({free} free); the oldest recycle-bin "
    "items may be permanently deleted to make room.\n"
)


class CountingS3Client(FakeS3Client):
    def __init__(self) -> None:
        super().__init__()
        self.head_calls: list[str] = []

    def head_object(self, Bucket, Key, **kwargs):
        self.head_calls.append(Key)
        return super().head_object(Bucket=Bucket, Key=Key, **kwargs)


@pytest.fixture
def fake_client() -> CountingS3Client:
    return CountingS3Client()


def limit(monkeypatch, free: int | None, purgeable: int | None = None) -> None:
    if free is not None:
        monkeypatch.setenv("STORAGE_FREE_BYTES", str(free))
    if purgeable is not None:
        monkeypatch.setenv("STORAGE_PURGEABLE_BYTES", str(purgeable))


def test_without_the_variables_a_write_of_any_size_goes_through_untouched(storage, fake_client, capsys):
    storage.write_bytes("big.bin", b"x" * 10_000)
    storage.copy("big.bin", "copy.bin")

    assert len(fake_client.objects) == 2
    assert fake_client.head_calls == []
    assert capsys.readouterr().err == ""


def test_a_write_that_fits_is_written_without_a_warning_or_an_extra_storage_call(
    monkeypatch, storage, fake_client, capsys
):
    limit(monkeypatch, free=100, purgeable=50)

    storage.write_bytes("a.bin", b"x" * 60)

    assert "a.bin" in fake_client.objects
    assert fake_client.head_calls == []
    assert capsys.readouterr().err == ""


def test_a_write_of_exactly_the_free_bytes_fits_and_one_byte_more_does_not(monkeypatch, storage, fake_client):
    limit(monkeypatch, free=10, purgeable=0)

    storage.write_bytes("fits.bin", b"x" * 10)
    with pytest.raises(StorageQuotaExceededError):
        storage.write_bytes("over.bin", b"x")

    assert "over.bin" not in fake_client.objects


def test_the_bytes_this_process_already_wrote_count_against_the_free_bytes(monkeypatch, storage, fake_client):
    limit(monkeypatch, free=100, purgeable=0)
    storage.write_bytes("first.bin", b"x" * 60)

    with pytest.raises(StorageQuotaExceededError):
        storage.write_bytes("second.bin", b"x" * 50)

    assert set(fake_client.objects) == {"first.bin"}


def test_a_write_that_needs_the_recycle_bin_is_written_after_the_exact_warning(
    monkeypatch, storage, fake_client, capsys
):
    limit(monkeypatch, free=40, purgeable=100)

    storage.write_bytes("a.bin", b"x" * 60)

    assert fake_client.objects["a.bin"]["Body"] == b"x" * 60
    assert capsys.readouterr().err == WARNING.format(free="40 B")


def test_purgeable_space_is_used_up_like_free_space(monkeypatch, storage, fake_client, capsys):
    limit(monkeypatch, free=40, purgeable=100)
    storage.write_bytes("a.bin", b"x" * 60)
    capsys.readouterr()

    storage.write_bytes("b.bin", b"x" * 30)
    assert capsys.readouterr().err == WARNING.format(free="0 B")

    with pytest.raises(StorageQuotaExceededError):
        storage.write_bytes("c.bin", b"x" * 60)
    assert set(fake_client.objects) == {"a.bin", "b.bin"}


@pytest.mark.parametrize(
    ("free", "shown"),
    [(512, "512 B"), (1536, "2 KB"), (3 * 1024 * 1024, "3.0 MB"), (int(1.5 * 1024 * 1024), "1.5 MB")],
)
def test_the_free_space_in_the_warning_is_human_readable(monkeypatch, storage, capsys, free, shown):
    limit(monkeypatch, free=free, purgeable=10 * 1024 * 1024)

    storage.write_bytes("a.bin", b"x" * (free + 1))

    assert capsys.readouterr().err == WARNING.format(free=shown)


def test_a_write_that_does_not_fit_even_with_the_bin_is_refused_before_anything_is_written(
    monkeypatch, storage, fake_client, capsys
):
    limit(monkeypatch, free=10, purgeable=20)

    with pytest.raises(StorageQuotaExceededError, match="Organization storage quota reached") as error:
        storage.write("a.txt", "x" * 40)

    assert fake_client.objects == {}
    assert "a.txt" in str(error.value)
    assert capsys.readouterr().err == ""


def test_the_refusal_is_not_a_size_limit_error_so_oversize_handlers_do_not_catch_it():
    from epicstaff_storage import StorageSizeLimitError

    assert not issubclass(StorageQuotaExceededError, StorageSizeLimitError)
    assert issubclass(StorageQuotaExceededError, RuntimeError)


def test_an_org_with_no_storage_left_refuses_every_write_including_empty_ones_and_folders(
    monkeypatch, storage, fake_client
):
    limit(monkeypatch, free=0, purgeable=0)

    for attempt in (
        lambda: storage.write("empty.txt", ""),
        lambda: storage.write_bytes("a.bin", b"x"),
        lambda: storage.mkdir("folder"),
    ):
        with pytest.raises(StorageQuotaExceededError, match="no storage is left"):
            attempt()

    assert fake_client.objects == {}


def test_overwriting_a_file_credits_its_current_size_looked_up_only_when_the_write_would_not_fit(
    monkeypatch, storage, fake_client, capsys
):
    fake_client.put_object(Bucket="b", Key="report.txt", Body=b"x" * 50)
    limit(monkeypatch, free=10, purgeable=0)

    storage.write_bytes("report.txt", b"y" * 55)

    assert fake_client.objects["report.txt"]["Body"] == b"y" * 55
    assert fake_client.head_calls == ["report.txt"]
    assert capsys.readouterr().err == ""


def test_an_overwrite_that_still_does_not_fit_after_the_credit_is_refused(monkeypatch, storage, fake_client):
    fake_client.put_object(Bucket="b", Key="report.txt", Body=b"x" * 50)
    limit(monkeypatch, free=10, purgeable=0)

    with pytest.raises(StorageQuotaExceededError):
        storage.write_bytes("report.txt", b"y" * 61)

    assert fake_client.objects["report.txt"]["Body"] == b"x" * 50


def test_an_overwrite_is_warned_about_only_for_the_bytes_it_adds(monkeypatch, storage, fake_client, capsys):
    fake_client.put_object(Bucket="b", Key="report.txt", Body=b"x" * 50)
    limit(monkeypatch, free=10, purgeable=100)

    storage.write_bytes("report.txt", b"y" * 70)

    assert capsys.readouterr().err == WARNING.format(free="10 B")


def test_appending_counts_the_whole_rewritten_file_less_the_old_one(monkeypatch, storage, fake_client):
    fake_client.put_object(Bucket="b", Key="log.txt", Body=b"x" * 30)
    limit(monkeypatch, free=60, purgeable=0)

    storage.append_text("log.txt", "y" * 50)

    assert fake_client.objects["log.txt"]["Body"] == b"x" * 30 + b"y" * 50


def test_appending_more_than_is_left_is_refused_and_leaves_the_file_as_it_was(monkeypatch, storage, fake_client):
    fake_client.put_object(Bucket="b", Key="log.txt", Body=b"x" * 30)
    limit(monkeypatch, free=40, purgeable=0)

    with pytest.raises(StorageQuotaExceededError):
        storage.append_text("log.txt", "y" * 50)

    assert fake_client.objects["log.txt"]["Body"] == b"x" * 30


def test_insert_and_edit_are_checked_like_any_other_write(monkeypatch, storage, fake_client):
    fake_client.put_object(Bucket="b", Key="doc.txt", Body=b"line one\n")
    limit(monkeypatch, free=2, purgeable=0)

    with pytest.raises(StorageQuotaExceededError):
        storage.insert_lines("doc.txt", 1, "a very long new line")
    with pytest.raises(StorageQuotaExceededError):
        storage.edit_line("doc.txt", 1, "line one", "a much longer line than before")

    assert fake_client.objects["doc.txt"]["Body"] == b"line one\n"


def test_a_copy_is_sized_by_its_source(monkeypatch, storage, fake_client):
    fake_client.put_object(Bucket="b", Key="src.bin", Body=b"x" * 60)
    limit(monkeypatch, free=40, purgeable=0)

    with pytest.raises(StorageQuotaExceededError):
        storage.copy("src.bin", "dst.bin")
    assert "dst.bin" not in fake_client.objects

    limit(monkeypatch, free=60, purgeable=0)
    storage.copy("src.bin", "dst.bin")
    assert fake_client.objects["dst.bin"]["Body"] == b"x" * 60


def test_a_move_that_does_not_fit_copies_nothing_and_deletes_nothing(monkeypatch, storage, fake_client):
    fake_client.put_object(Bucket="b", Key="src.bin", Body=b"x" * 60)
    limit(monkeypatch, free=10, purgeable=0)

    with pytest.raises(StorageQuotaExceededError):
        storage.move("src.bin", "dst.bin")

    assert set(fake_client.objects) == {"src.bin"}


def test_a_failed_write_does_not_use_up_the_free_bytes(monkeypatch, storage, fake_client):
    limit(monkeypatch, free=100, purgeable=0)

    with pytest.raises(StorageQuotaExceededError):
        storage.write_bytes("too-big.bin", b"x" * 101)
    storage.write_bytes("fits.bin", b"x" * 100)

    assert "fits.bin" in fake_client.objects


def test_a_write_of_exactly_the_free_plus_purgeable_bytes_is_warned_about_and_one_more_byte_is_refused(
    monkeypatch, storage, fake_client, capsys
):
    limit(monkeypatch, free=10, purgeable=20)

    storage.write_bytes("exact.bin", b"x" * 30)
    assert capsys.readouterr().err == WARNING.format(free="10 B")

    with pytest.raises(StorageQuotaExceededError):
        storage.write_bytes("over.bin", b"x")
    assert set(fake_client.objects) == {"exact.bin"}


def _failing_head(monkeypatch, fake_client):
    from fakes import make_client_error

    def deny(**kwargs):
        raise make_client_error("403", "HeadObject")

    monkeypatch.setattr(fake_client, "head_object", deny)


def test_a_copy_whose_source_size_cannot_be_read_goes_ahead_while_free_bytes_remain(
    monkeypatch, storage, fake_client
):
    fake_client.put_object(Bucket="b", Key="src.bin", Body=b"x" * 60)
    limit(monkeypatch, free=100, purgeable=0)
    _failing_head(monkeypatch, fake_client)

    storage.copy("src.bin", "dst.bin")

    assert "dst.bin" in fake_client.objects


def test_a_copy_whose_source_size_cannot_be_read_is_refused_once_no_free_byte_is_left(
    monkeypatch, storage, fake_client
):
    fake_client.put_object(Bucket="b", Key="src.bin", Body=b"x" * 60)
    limit(monkeypatch, free=10, purgeable=0)
    storage.write_bytes("fills.bin", b"x" * 10)
    _failing_head(monkeypatch, fake_client)

    with pytest.raises(StorageQuotaExceededError):
        storage.copy("src.bin", "dst.bin")

    assert "dst.bin" not in fake_client.objects
