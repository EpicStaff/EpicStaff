"""The plugin process's view of its runtime file (`epicstaff_plugin.contracts.runtime`)."""

import logging
import os
import threading
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pydantic import ValidationError

from epicstaff_plugin.contracts.gateway_context import Jwks
from epicstaff_plugin.contracts.manifest import PublicPath
from epicstaff_plugin.contracts.runtime import (
    RUNTIME_FILE_ENVIRONMENT_VARIABLE,
    RuntimeFile,
    SettingValue,
)
from epicstaff_plugin.problems import format_loc

logger = logging.getLogger(__name__)

# What identifies one written version of the file: the node replaces it with a rename, which
# gives a new inode, and a rewrite in place changes the modification time.
_FileStamp = tuple[int, int, int]


class RuntimeConfigError(Exception):
    """The runtime file is not named, cannot be read, or does not hold a valid runtime file."""


class RuntimeConfig:
    """The runtime file of this plugin process, re-read whenever the file changes.

    The node agent rewrites the file atomically when EpicStaff's signing keys rotate. Every
    accessor first checks the file's inode and modification time and re-reads it when either
    changed. Once the first read succeeded, a later file that cannot be read or does not
    validate is logged and the previous content stays in use, so a bad rewrite cannot take a
    running plugin down.

    The file holds secret settings: never log or return the whole document to a caller.
    """

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._stamp, self._document = _read_runtime_file(path)

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "RuntimeConfig":
        """Read the runtime file at `path`, by default the one `EPICSTAFF_PLUGIN_RUNTIME_FILE` names.

        Raises:
            RuntimeConfigError: No path is given or named, or the file is unreadable or invalid.
        """
        return cls(Path(path) if path is not None else runtime_file_path())

    @property
    def path(self) -> Path:
        return self._path

    @property
    def document(self) -> RuntimeFile:
        """The current content of the runtime file; a new object each time the file changed."""
        try:
            stamp = _stamp(os.stat(self._path))
        except OSError as error:
            logger.warning("Cannot check the runtime file %s: %s", self._path, error.strerror)
            return self._document
        if stamp != self._stamp:
            self._reload(stamp)
        return self._document

    @property
    def plugin_identifier(self) -> str:
        return self.document.plugin.identifier

    @property
    def plugin_version(self) -> str:
        return self.document.plugin.version

    @property
    def issuer(self) -> str:
        return self.document.issuer

    @property
    def public_url(self) -> str:
        """The plugin's public address; build external callback addresses from it."""
        return self.document.public_url

    @property
    def epicstaff_public_url(self) -> str:
        return self.document.epicstaff_public_url

    @property
    def epicstaff_api_url(self) -> str:
        return self.document.epicstaff_api_url

    @property
    def settings(self) -> Mapping[str, SettingValue]:
        """Every non-secret setting: its stored value, else its default; unset optional ones left out."""
        return MappingProxyType(self.document.settings)

    @property
    def secret_settings(self) -> Mapping[str, str]:
        """The secret settings that are set."""
        return MappingProxyType(self.document.secret_settings)

    @property
    def service_accounts(self) -> Mapping[str, Any]:
        return MappingProxyType(self.document.service_accounts)

    @property
    def jwks(self) -> Jwks:
        return self.document.jwks

    @property
    def public_paths(self) -> tuple[PublicPath, ...]:
        return tuple(self.document.public_paths)

    def setting(self, key: str, default: SettingValue | None = None) -> SettingValue | None:
        """Return a non-secret setting, or `default` when it is optional and neither set nor defaulted."""
        return self.document.settings.get(key, default)

    def secret_setting(self, key: str) -> str | None:
        """Return a secret setting, or None when it is not set."""
        return self.document.secret_settings.get(key)

    def _reload(self, stamp: _FileStamp) -> None:
        with self._lock:
            if stamp == self._stamp:
                return
            try:
                self._stamp, self._document = _read_runtime_file(self._path)
            except RuntimeConfigError as error:
                logger.warning("Keeping the previous runtime file: %s", error)
                # Not retried until the file changes again: the node only ever replaces it.
                self._stamp = stamp


_shared: dict[Path, RuntimeConfig] = {}
_shared_lock = threading.Lock()


def runtime_config() -> RuntimeConfig:
    """Return this process's runtime configuration, shared by the SDK and the plugin's code.

    Loaded on first use from the file `EPICSTAFF_PLUGIN_RUNTIME_FILE` names.
    `python -m epicstaff_plugin.serve` loads it before the app starts, so the context check and
    the plugin read one instance.

    Raises:
        RuntimeConfigError: The variable is not set, or the file is unreadable or invalid.
    """
    path = runtime_file_path()
    with _shared_lock:
        config = _shared.get(path)
        if config is None:
            config = _shared[path] = RuntimeConfig(path)
    return config


def runtime_file_path() -> Path:
    """Return the runtime file `EPICSTAFF_PLUGIN_RUNTIME_FILE` names.

    Raises:
        RuntimeConfigError: The variable is not set.
    """
    value = os.environ.get(RUNTIME_FILE_ENVIRONMENT_VARIABLE)
    if not value:
        raise RuntimeConfigError(
            f"{RUNTIME_FILE_ENVIRONMENT_VARIABLE} is not set; the EpicStaff node sets it for "
            "every plugin process"
        )
    return Path(value)


def _read_runtime_file(path: Path) -> tuple[_FileStamp, RuntimeFile]:
    try:
        with path.open("rb") as stream:
            stamp = _stamp(os.fstat(stream.fileno()))
            raw = stream.read()
    except OSError as error:
        raise RuntimeConfigError(f"cannot read {path}: {error.strerror}") from None
    try:
        return stamp, RuntimeFile.model_validate_json(raw, extra="ignore")
    except ValidationError as error:
        # Built without the offending values: the file holds secrets.
        details = "; ".join(
            f"{format_loc('runtime', detail['loc'])}: {detail['msg']}"
            for detail in error.errors(
                include_url=False, include_input=False, include_context=False
            )
        )
        raise RuntimeConfigError(f"{path} is not a valid runtime file: {details}") from None


def _stamp(status: os.stat_result) -> _FileStamp:
    return (status.st_ino, status.st_mtime_ns, status.st_size)
