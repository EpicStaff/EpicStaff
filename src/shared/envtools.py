import os
from pathlib import Path
from types import EllipsisType
from typing import Any, Callable
from . import humanize

__all__ = [
    "EnvironmentNotFoundError",
    "Env",
]


class EnvironmentNotFoundError(Exception):
    pass


class Env:
    BOOLEAN_TRUE_VALUES = frozenset({"1", "y", "yes", "true", "on"})
    EMPTY_SENTINEL = "__empty__"

    def __init__(self):
        self._envs: dict[str, str] = {}
        self._envs.update(os.environ)

    def __contains__(self, variable):
        return variable in self._envs

    def read_env(self, env_file: Path | str, override=False):
        env_file = Path(env_file)

        if not env_file.exists():
            raise ValueError(f"Not found file in {env_file}")

        if not env_file.is_file():
            raise TypeError("Path must point on file.")

        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            variable, separator, value = line.partition("=")
            if not separator:
                continue

            variable = variable.strip()
            value = value.strip(" \"\'")

            if override or variable not in self._envs:
                self._envs[variable] = value

    def get_value(
        self,
        variable: str,
        default: Any | None | EllipsisType = ...,
        cast: Callable[[Any], Any] = lambda v: v,
    ) -> Any | None:
        """Look up an environment variable and cast its value.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing; if omitted, a
                missing variable raises instead.
            cast: Callable applied to the raw string value before returning.

        Returns:
            The cast value; None when the variable holds the ``__empty__`` sentinel;
            otherwise ``default`` or None when the variable is missing.

        Raises:
            EnvironmentNotFoundError: The variable is missing and no ``default`` was
                provided.
        """
        value = self._envs.get(variable)
        if value == self.EMPTY_SENTINEL:
            return None
        elif value is not None:
            return cast(value)
        elif default is not ...:
            return default
        else:
            raise EnvironmentNotFoundError(f"Not found environment: {variable}.")

    def dns(
        self,
        provider: str,
        host: str,
        port: str,
        user: str,
        password: str,
        name: str,
        default: str | EllipsisType = ...,
    ) -> str | None:
        """Assemble a DSN connection string from environment variables.

        Args:
            provider: URL scheme, e.g. ``postgres`` or ``redis``.
            host: Name of the env var holding the host.
            port: Name of the env var holding the port.
            user: Name of the env var holding the user; blank when unset.
            password: Name of the env var holding the password; blank when unset.
            name: Name of the env var holding the database name.
            default: Value returned when a required var is missing.

        Returns:
            The ``provider://user:password@host:port/name`` string, or ``default``
            when a required var is missing.

        Raises:
            EnvironmentNotFoundError: A required var is missing and no ``default`` was
                provided.
        """
        try:
            host = self.str(host)
            port = self.int(port)
            name = self.str(name)
            user = self.str(user, "")
            password = self.str(password, "")

        except EnvironmentNotFoundError:
            if default is not ...:
                return default
            raise
        else:
            credential = f"{user}:{password}@" if user or password else ""
            return f"{provider}://{credential}{host}:{port}/{name}"

    def time(self, variable: str, default: float | EllipsisType = ...) -> float | None:
        """Read an environment variable as a duration in seconds.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.

        Returns:
            The duration in seconds, or None when the variable holds the ``__empty__``
            sentinel.
        """
        return self.get_value(variable, default, humanize.to_time)

    def byte_size(self, variable: str, default: int | EllipsisType = ...) -> int | None:
        """Read an environment variable as a byte size.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.

        Returns:
            The size in bytes, or None when the variable holds the ``__empty__``
            sentinel.
        """
        return self.get_value(variable, default, humanize.to_byte_size)

    def path(self, variable: str, default: Path | EllipsisType = ...) -> Path | None:
        """Read an environment variable as a filesystem path.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.

        Returns:
            The path, or None when the variable holds the ``__empty__`` sentinel.
        """
        return self.get_value(variable, default, Path)

    def list(self, variable: str, default: list | EllipsisType = ..., split=",") -> list | None:
        """Read an environment variable as a delimited list of strings.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.
            split: Delimiter used to split the raw value.

        Returns:
            The list of stripped items, or None when the variable holds the
            ``__empty__`` sentinel.
        """
        cast = lambda v: [s.strip() for s in v.strip().split(split)]
        return self.get_value(variable, default, cast)

    def int(self, variable: str, default: int | EllipsisType = ...) -> int | None:
        """Read an environment variable as an int.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.

        Returns:
            The int value, or None when the variable holds the ``__empty__`` sentinel.
        """
        return self.get_value(variable, default, int)

    def float(self, variable: str, default: float | EllipsisType = ...) -> float | None:
        """Read an environment variable as a float.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.

        Returns:
            The float value, or None when the variable holds the ``__empty__``
            sentinel.
        """
        return self.get_value(variable, default, float)

    def bool(self, variable: str, default: bool | EllipsisType = ...) -> bool | None:
        """Read an environment variable as a bool.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.

        Returns:
            True when the raw value is one of ``BOOLEAN_TRUE_VALUES``; None when the
            variable holds the ``__empty__`` sentinel.
        """
        cast = lambda v: v.lower() in self.BOOLEAN_TRUE_VALUES
        return self.get_value(variable, default, cast)

    def str(self, variable: str, default: str | EllipsisType = ...) -> str | None:
        """Read an environment variable as a str.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.

        Returns:
            The string value, or None when the variable holds the ``__empty__``
            sentinel.
        """
        return self.get_value(variable, default, str)
