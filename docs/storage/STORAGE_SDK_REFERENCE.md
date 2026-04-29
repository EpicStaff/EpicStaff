# EpicStaff Storage SDK Reference

Developer reference for the `EpicStaffStorage` SDK available inside **Python nodes** and **Code Agent nodes** in flows.

Source: `src/shared/epicstaff_storage/storage.py`

---

## Table of Contents

1. [Availability](#availability)
2. [Environment Variables](#environment-variables)
3. [Permission Model](#permission-model)
4. [API Reference](#api-reference)
   - [read](#read)
   - [read\_bytes](#read_bytes)
   - [write](#write)
   - [write\_bytes](#write_bytes)
   - [list](#list)
   - [exists](#exists)
   - [delete](#delete)
   - [mkdir](#mkdir)
   - [move](#move)
   - [copy](#copy)
   - [info](#info)
   - [as\_local](#as_local)
5. [Mutation Tracking](#mutation-tracking)
6. [Exceptions](#exceptions)
7. [Examples](#examples)

---

## Availability

Set `use_storage=True` on a `PythonNode` or `CodeAgentNode`. The execution stack injects an `EpicStaffStorage` instance as the variable `storage` into the node's execution context.

```python
# Inside a Python node or Code Agent node with use_storage=True
content = storage.read("reports/summary.txt")
```

`storage` is not available when `use_storage=False` (the default).

---

## Environment Variables

Injected at runtime by the execution stack. Node code does not need to set these.

| Variable | Description |
|----------|-------------|
| `STORAGE_ENDPOINT` | S3/MinIO endpoint URL |
| `STORAGE_ACCESS_KEY` | S3 access key |
| `STORAGE_SECRET_KEY` | S3 secret key |
| `STORAGE_BUCKET_NAME` | S3 bucket name |
| `STORAGE_ORG_PREFIX` | Organization prefix (e.g. `org_1`). Auto-prepended to all paths — node code uses relative paths only. |
| `STORAGE_ALLOWED_PATHS` | JSON array of paths this flow may access. If absent, all paths are accessible. |

All paths passed to SDK methods are **relative** (e.g. `reports/output.csv`). The org prefix is added transparently by `_normalize_key`.

---

## Permission Model

Every SDK method calls `check_storage_permission` before touching storage.

**Path traversal** — paths containing `../` after normalization raise `StoragePermissionError` immediately. Leading slashes are stripped before the check.

**Allowlist** — controlled by `STORAGE_ALLOWED_PATHS` (a JSON array set by the flow configuration).

- If `STORAGE_ALLOWED_PATHS` is not set, all paths are accessible.
- If set, only listed paths (and their children, for folder entries) are accessible.
- A folder entry in the allowlist must end with `/` to grant access to children.

```json
// STORAGE_ALLOWED_PATHS examples
["reports/output.csv"]                   // exact file only
["reports/"]                             // reports/ folder and all contents
["reports/output.csv", "data/input.csv"] // two specific files
```

Denied operations raise `StoragePermissionError` with message:

```
Access denied: <operation> on '<path>' — not in this flow's allowed files.
```

---

## API Reference

### `read`

```python
def read(self, path: str) -> str
```

Read a file and return its contents as a UTF-8 string.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str` | Relative path to the file |

**Returns:** `str` — file contents decoded as UTF-8.

**Raises:** `FileNotFoundError` if the key does not exist. `StoragePermissionError` if access is denied.

---

### `read_bytes`

```python
def read_bytes(self, path: str) -> bytes
```

Read a file and return its raw bytes.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str` | Relative path to the file |

**Returns:** `bytes`

**Raises:** `FileNotFoundError`, `StoragePermissionError`

---

### `write`

```python
def write(self, path: str, content: str) -> None
```

Write a UTF-8 string to a file. Creates or overwrites. Records a `write` mutation.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str` | Relative path to the file |
| `content` | `str` | UTF-8 string to write |

**Raises:** `StoragePermissionError`

---

### `write_bytes`

```python
def write_bytes(self, path: str, content: bytes) -> None
```

Write raw bytes to a file. Creates or overwrites. Records a `write` mutation.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str` | Relative path to the file |
| `content` | `bytes` | Raw bytes to write |

**Raises:** `StoragePermissionError`

---

### `list`

```python
def list(self, path: str) -> list[dict]
```

List the contents of a folder (one level deep, non-recursive). `.keep` marker files are excluded from results.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str` | Relative path to the folder |

**Returns:** List of entry dicts:

| Key | Type | Description |
|-----|------|-------------|
| `name` | `str` | File or folder name |
| `type` | `str` | `"file"` or `"folder"` |
| `size` | `int` | Size in bytes (`0` for folders) |
| `modified` | `str \| None` | ISO 8601 timestamp or `None` |

**Raises:** `StoragePermissionError`

---

### `exists`

```python
def exists(self, path: str) -> bool
```

Check whether a file or folder exists.

For folders, falls back to a prefix listing if the direct HEAD request returns 404. Returns `True` if any objects exist under the prefix.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str` | Relative path to check |

**Returns:** `bool`

**Raises:** `StoragePermissionError`, `RuntimeError` on unexpected storage errors.

---

### `delete`

```python
def delete(self, path: str) -> None
```

Delete a file. Records a `delete` mutation.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str` | Relative path to the file |

**Raises:** `StoragePermissionError`

---

### `mkdir`

```python
def mkdir(self, path: str) -> None
```

Create a folder by writing a `.keep` marker object. S3-compatible storage has no native folder concept; this ensures the folder is visible in listings.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str` | Relative path for the new folder |

**Raises:** `StoragePermissionError`

---

### `move`

```python
def move(self, src: str, dst: str) -> None
```

Move a file. Implemented as `copy` + `delete`. Both source and destination paths are permission-checked independently.

| Parameter | Type | Description |
|-----------|------|-------------|
| `src` | `str` | Source path |
| `dst` | `str` | Destination path |

**Raises:** `StoragePermissionError` for either path. `FileNotFoundError` if source does not exist.

---

### `copy`

```python
def copy(self, src: str, dst: str) -> None
```

Server-side S3 copy. Both source and destination paths are permission-checked. Records a `write` mutation for the destination.

| Parameter | Type | Description |
|-----------|------|-------------|
| `src` | `str` | Source path |
| `dst` | `str` | Destination path |

**Raises:** `StoragePermissionError` for either path. `FileNotFoundError` if source does not exist.

---

### `info`

```python
def info(self, path: str) -> dict
```

Return metadata for a file.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str` | Relative path to the file |

**Returns:**

| Key | Type | Description |
|-----|------|-------------|
| `name` | `str` | File name (last path segment) |
| `size` | `int` | Size in bytes |
| `content_type` | `str` | MIME type reported by S3 |
| `modified` | `str \| None` | ISO 8601 timestamp or `None` |

**Raises:** `FileNotFoundError`, `StoragePermissionError`

---

### `as_local`

```python
@contextmanager
def as_local(self, path: str) -> Generator[str, None, None]
```

Context manager. Downloads the file to a temporary location, yields the local file path, then deletes the temp file on exit. Use this when a library requires a real filesystem path instead of bytes.

The temp file preserves the original file extension.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str` | Relative path to the file |

**Yields:** `str` — absolute path to the temporary local file.

**Raises:** `StoragePermissionError`, `FileNotFoundError`

```python
with storage.as_local("models/classifier.pkl") as local_path:
    import joblib
    model = joblib.load(local_path)
    result = model.predict(data)
```

---

## Mutation Tracking

`write`, `write_bytes`, `copy`, and `delete` record mutations. These are used by the session tracking layer to create `SessionStorageFile` records after a node finishes.

```python
from epicstaff_storage.storage import get_mutations, clear_mutations

mutations = get_mutations()
# [{"op": "write", "path": "org_1/reports/output.csv"}, ...]

clear_mutations()
```

Each mutation record:

| Key | Type | Description |
|-----|------|-------------|
| `op` | `str` | `"write"` or `"delete"` |
| `path` | `str` | Full S3 key including org prefix |

`get_mutations()` returns a copy of the list. Node code generally does not need to call these functions — the execution stack handles them automatically.

---

## Exceptions

| Exception | Raised when |
|-----------|-------------|
| `StoragePermissionError` | Path not in allowlist, or path traversal (`../`) detected |
| `FileNotFoundError` | Object does not exist in storage (`read`, `read_bytes`, `info`, `move`, `copy`) |
| `EnvironmentError` | Required env vars (`STORAGE_ENDPOINT`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `STORAGE_BUCKET_NAME`) are missing on first client init |
| `RuntimeError` | Unexpected S3/boto3 error wrapping an unrecognized `ClientError` or generic exception |

`StoragePermissionError` is a subclass of `PermissionError`.

---

## Examples

### Read and write a text file

```python
# Read
content = storage.read("data/config.json")

# Write
storage.write("results/output.txt", "Processing complete.\n")
```

### Read and write binary data

```python
# Read image bytes
image_bytes = storage.read_bytes("images/photo.png")

# Write processed bytes
storage.write_bytes("images/photo_thumb.png", thumbnail_bytes)
```

### List directory contents

```python
entries = storage.list("reports/")

for entry in entries:
    print(entry["name"], entry["type"], entry["size"])

# Filter to files only
files = [e for e in entries if e["type"] == "file"]
```

### Check existence before operating

```python
if storage.exists("cache/result.json"):
    cached = storage.read("cache/result.json")
else:
    result = run_expensive_computation()
    storage.write("cache/result.json", result)
    cached = result
```

### Use a file with a library requiring a local path

```python
import pandas as pd

with storage.as_local("data/sales.csv") as local_path:
    df = pd.read_csv(local_path)

summary = df.groupby("region")["revenue"].sum()
storage.write("reports/summary.csv", summary.to_csv())
```

### Create a folder and write multiple files

```python
storage.mkdir("run_outputs/")

for index, item in enumerate(results):
    storage.write(f"run_outputs/item_{index}.txt", item)
```

### Move a processed file to an archive folder

```python
storage.mkdir("archive/")
storage.move("inbox/report.pdf", "archive/report.pdf")
```

### Get file metadata

```python
meta = storage.info("reports/output.csv")
print(meta["size"])         # bytes
print(meta["content_type"]) # e.g. "text/csv"
print(meta["modified"])     # ISO 8601 string or None
```
