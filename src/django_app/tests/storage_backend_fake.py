"""An in-memory storage backend with the calls the transfer archive store makes."""


class FakeStorageBackend:
    """In-memory storage with the calls the store makes; records each read's size."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.chunk_sizes_read: list[int] = []

    def upload_stream(self, path: str, file_object) -> None:
        self.objects[path] = file_object.read()

    def iter_object(self, path: str, chunk_size: int):
        if path not in self.objects:
            raise FileNotFoundError(path)
        data = self.objects[path]
        for start in range(0, len(data), chunk_size):
            chunk = data[start : start + chunk_size]
            self.chunk_sizes_read.append(len(chunk))
            yield chunk

    def delete_prefix(self, prefix: str) -> None:
        for key in [key for key in self.objects if key.startswith(prefix)]:
            del self.objects[key]
