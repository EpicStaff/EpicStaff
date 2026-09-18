"""In-memory fake of the subset of the boto3 S3 client surface used by
``epicstaff_storage.storage``. No network, no moto — just a dict of keys.
"""

from __future__ import annotations

from datetime import datetime, timezone


class FakeClientError(Exception):
    """Stand-in for botocore.exceptions.ClientError.

    ``_handle_client_error`` in storage.py does
    ``from botocore.exceptions import ClientError`` and ``isinstance(error, ClientError)``.
    Since botocore *is* installed in this environment (boto3's own dependency),
    we raise the real ClientError so that isinstance check behaves exactly like
    it would against a real S3/MinIO error response.
    """


def make_client_error(code: str, operation_name: str = "FakeOperation"):
    from botocore.exceptions import ClientError

    return ClientError(
        error_response={"Error": {"Code": code, "Message": code}},
        operation_name=operation_name,
    )


class FakeS3Client:
    """Minimal in-memory S3 client fake.

    Supports get_object / put_object / delete_object / delete_objects /
    copy_object / head_object / list_objects_v2 (with Delimiter and
    ContinuationToken/MaxKeys pagination).

    ``page_size`` forces list_objects_v2 to paginate in chunks of that size
    regardless of the caller-supplied MaxKeys, so tests can exercise
    multi-page walks/deletes deterministically.

    Failure injection for ``delete_objects`` (both opt-in, default
    behavior unchanged):

    - ``fail_delete_objects_on_call``: 1-indexed call number on which
      ``delete_objects`` raises a ``ClientError`` instead of returning a
      response — simulates the whole batch call failing outright (no
      per-key result available).
    - ``delete_objects_error_keys``: a set of keys that, whenever present
      in a ``delete_objects`` batch, are left undeleted and reported back
      in ``response["Errors"]`` instead of ``response["Deleted"]`` —
      simulates boto3's HTTP-200-with-per-key-failures shape. Any other
      key in the same batch is still deleted and reported normally.
    """

    def __init__(self, page_size: int = 1000) -> None:
        self.objects: dict[str, dict] = {}
        self.page_size = page_size
        self.delete_objects_calls: list[list[str]] = []
        self.fail_delete_objects_on_call: int | None = None
        self.fail_delete_objects_error_code: str = "InternalError"
        self.delete_objects_error_keys: set[str] = set()

    def put_object(self, Bucket, Key, Body, **kwargs):
        data = Body if isinstance(Body, bytes) else str(Body).encode("utf-8")
        self.objects[Key] = {
            "Body": data,
            "LastModified": datetime.now(timezone.utc),
            "ContentType": kwargs.get("ContentType", "binary/octet-stream"),
        }
        return {}

    def get_object(self, Bucket, Key, **kwargs):
        if Key not in self.objects:
            raise make_client_error("NoSuchKey")
        obj = self.objects[Key]
        return {
            "Body": _FakeBody(obj["Body"]),
            "ContentType": obj["ContentType"],
            "LastModified": obj["LastModified"],
        }

    def head_object(self, Bucket, Key, **kwargs):
        if Key not in self.objects:
            raise make_client_error("404")
        obj = self.objects[Key]
        return {
            "ContentLength": len(obj["Body"]),
            "ContentType": obj["ContentType"],
            "LastModified": obj["LastModified"],
        }

    def delete_object(self, Bucket, Key, **kwargs):
        self.objects.pop(Key, None)
        return {}

    def delete_objects(self, Bucket, Delete, **kwargs):
        keys = [ref["Key"] for ref in Delete.get("Objects", [])]
        self.delete_objects_calls.append(keys)
        call_number = len(self.delete_objects_calls)

        if (
            self.fail_delete_objects_on_call is not None
            and call_number == self.fail_delete_objects_on_call
        ):
            raise make_client_error(self.fail_delete_objects_error_code)

        deleted = []
        errors = []
        for key in keys:
            if key in self.delete_objects_error_keys:
                errors.append(
                    {"Key": key, "Code": "InternalError", "Message": "Simulated failure"}
                )
                continue
            if key in self.objects:
                del self.objects[key]
            deleted.append({"Key": key})

        response: dict = {"Deleted": deleted}
        if errors:
            response["Errors"] = errors
        return response

    def copy_object(self, Bucket, CopySource, Key, **kwargs):
        src_key = CopySource["Key"]
        if src_key not in self.objects:
            raise make_client_error("NoSuchKey")
        self.objects[Key] = dict(self.objects[src_key])
        self.objects[Key]["LastModified"] = datetime.now(timezone.utc)
        return {}

    def list_objects_v2(
        self,
        Bucket,
        Prefix: str = "",
        Delimiter: str | None = None,
        MaxKeys: int | None = None,
        ContinuationToken: str | None = None,
        **kwargs,
    ):
        matching_keys = sorted(k for k in self.objects if k.startswith(Prefix))

        effective_max = MaxKeys if MaxKeys is not None else self.page_size
        effective_max = min(effective_max, self.page_size)

        start_index = int(ContinuationToken) if ContinuationToken else 0
        window = matching_keys[start_index:]

        contents: list[dict] = []
        common_prefixes: set[str] = set()
        consumed = 0
        next_index: int | None = None

        for offset, key in enumerate(window):
            if consumed >= effective_max:
                next_index = start_index + offset
                break

            remainder = key[len(Prefix) :]
            if Delimiter and Delimiter in remainder:
                folder = remainder.split(Delimiter, 1)[0]
                common_prefixes.add(Prefix + folder + Delimiter)
            else:
                obj = self.objects[key]
                contents.append(
                    {
                        "Key": key,
                        "Size": len(obj["Body"]),
                        "LastModified": obj["LastModified"],
                    }
                )
            consumed += 1

        is_truncated = next_index is not None
        response = {
            "Contents": contents,
            "CommonPrefixes": [{"Prefix": p} for p in sorted(common_prefixes)],
            "IsTruncated": is_truncated,
            "KeyCount": consumed,
        }
        if is_truncated:
            response["NextContinuationToken"] = str(next_index)
        return response


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data
