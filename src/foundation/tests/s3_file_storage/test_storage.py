import pytest

from foundation.s3_file_storage import errors


class TestS3FileStorage:
    def test_buckets_includes_a_newly_created_bucket(self, storage, bucket_name):
        storage.bucket(bucket_name).create()
        assert bucket_name in [b.name for b in storage.buckets()]

    def test_buckets_respects_max(self, storage, bucket_name):
        for i in range(5):
            storage.bucket(f"{bucket_name}-{i}").create()
        assert len(storage.buckets(max=3)) == 3

    @pytest.mark.asyncio
    async def test_abuckets_matches_sync(self, storage, bucket_name):
        storage.bucket(bucket_name).create()
        sync_names = {b.name for b in storage.buckets()}
        async_names = {b.name for b in await storage.abuckets()}
        assert async_names == sync_names
        assert bucket_name in async_names


class TestBucket:
    def test_exist_false_when_missing(self, storage, bucket_name):
        assert storage.bucket(bucket_name).exist() is False

    def test_create_then_exist_true(self, storage, bucket_name):
        bucket = storage.bucket(bucket_name)
        bucket.create()
        assert bucket.exist() is True

    def test_create_is_idempotent_on_rustfs(self, storage, bucket_name):
        """Unlike AWS S3, RustFS 1.0.0 answers a repeat create_bucket for the same owner with a
        plain success (confirmed against the real server), not BucketAlreadyOwnedByYou -- so
        S3BucketAlreadyExistsError is not reachable this way against this backend."""
        bucket = storage.bucket(bucket_name)
        bucket.create()
        bucket.create()
        assert bucket.exist() is True

    def test_delete_missing_raises_not_exist(self, storage, bucket_name):
        with pytest.raises(errors.S3BucketNotExistError):
            storage.bucket(bucket_name).delete()

    def test_delete_removes_it(self, storage, bucket_name):
        bucket = storage.bucket(bucket_name)
        bucket.create()
        bucket.delete()
        assert bucket.exist() is False

    def test_object_returns_handle_without_checking_existence(self, storage, bucket_name):
        obj = storage.bucket(bucket_name).object("key.txt")
        assert obj.bucket == bucket_name
        assert obj.key == "key.txt"

    @pytest.mark.asyncio
    async def test_async_crud_matches_sync(self, storage, bucket_name):
        bucket = storage.bucket(bucket_name)
        assert await bucket.aexist() is False
        await bucket.acreate()
        assert await bucket.aexist() is True
        await bucket.adelete()
        assert await bucket.aexist() is False


class TestBucketObjects:
    def test_lists_and_filters_by_prefix(self, storage, bucket_name):
        bucket = storage.bucket(bucket_name)
        bucket.create()
        bucket.object("logs/a.txt").write(b"1")
        bucket.object("logs/b.txt").write(b"2")
        bucket.object("other.txt").write(b"3")
        assert sorted(o.key for o in bucket.objects(prefix="logs/")) == ["logs/a.txt", "logs/b.txt"]

    def test_respects_max(self, storage, bucket_name):
        bucket = storage.bucket(bucket_name)
        bucket.create()
        for i in range(5):
            bucket.object(f"key-{i}").write(b"x")
        assert len(bucket.objects(max=2)) == 2

    def test_empty_bucket_returns_empty_list(self, storage, bucket_name):
        bucket = storage.bucket(bucket_name)
        bucket.create()
        assert bucket.objects() == []

    @pytest.mark.asyncio
    async def test_aobjects_matches_sync(self, storage, bucket_name):
        bucket = storage.bucket(bucket_name)
        bucket.create()
        bucket.object("k").write(b"v")
        result = await bucket.aobjects()
        assert [o.key for o in result] == ["k"]

    @pytest.mark.slow
    def test_paginates_across_real_server_pages(self, storage, bucket_name):
        """boto3's ListObjectsV2 default page size is 1000 -- 1001 real objects forces a
        second real round trip through the paginator, not just our own loop logic."""
        bucket = storage.bucket(bucket_name)
        bucket.create()
        total = 1001
        for i in range(total):
            bucket.object(f"k/{i:05d}").write(b"")
        assert len(bucket.objects()) == total


class TestObject:
    def test_exist_false_when_missing(self, storage, bucket_name):
        storage.bucket(bucket_name).create()
        assert storage.bucket(bucket_name).object("missing.txt").exist() is False

    def test_exist_false_when_bucket_itself_is_missing(self, storage, bucket_name):
        assert storage.bucket(bucket_name).object("key.txt").exist() is False

    def test_write_then_read_round_trips(self, storage, bucket_name):
        storage.bucket(bucket_name).create()
        obj = storage.bucket(bucket_name).object("file.txt")
        obj.write(b"hello world")
        assert obj.exist() is True
        assert obj.read() == b"hello world"

    def test_write_overwrites_existing(self, storage, bucket_name):
        storage.bucket(bucket_name).create()
        obj = storage.bucket(bucket_name).object("file.txt")
        obj.write(b"first")
        obj.write(b"second")
        assert obj.read() == b"second"

    def test_delete_removes_it(self, storage, bucket_name):
        storage.bucket(bucket_name).create()
        obj = storage.bucket(bucket_name).object("file.txt")
        obj.write(b"data")
        obj.delete()
        assert obj.exist() is False

    def test_delete_missing_key_is_a_noop(self, storage, bucket_name):
        storage.bucket(bucket_name).create()
        storage.bucket(bucket_name).object("missing.txt").delete()

    def test_read_missing_raises_not_exist(self, storage, bucket_name):
        storage.bucket(bucket_name).create()
        with pytest.raises(errors.S3ObjectNotExistError):
            storage.bucket(bucket_name).object("missing.txt").read()

    @pytest.mark.asyncio
    async def test_async_crud_matches_sync(self, storage, bucket_name):
        storage.bucket(bucket_name).create()
        obj = storage.bucket(bucket_name).object("file.txt")
        await obj.awrite(b"async-data")
        assert await obj.aexist() is True
        assert await obj.aread() == b"async-data"
        await obj.adelete()
        assert await obj.aexist() is False
