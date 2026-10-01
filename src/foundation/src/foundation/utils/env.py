import ast
import os
from collections.abc import Callable
from pathlib import Path
from types import EllipsisType
from typing import Any

from . import humanize

__all__ = ["Env", "EnvironmentBlankError", "EnvironmentNotFoundError"]

type Str = str
type Bool = bool
type Float = float
type Int = int
type Dict = dict
type List = list


class EnvironmentNotFoundError(Exception):
    """Raised when a required environment variable is missing."""


class EnvironmentBlankError(Exception):
    """Raised when a required secret is present but empty or whitespace-only."""


def _to_dict(value: Str) -> Dict:
    """Parse an environment value into a dict.

    Two formats are accepted:
    - a comma-separated list of ``key=value`` pairs, e.g. ``"a=1,b=2"`` (values
      are always strings);
    - a Python/JSON dict literal, e.g. ``"{'a': '1', 'b': 2}"`` (values keep
      their literal types).

    Raises:
        ValueError: The value starts like a dict literal but does not parse to a
            dict.
    """
    stripped = value.strip()
    if stripped.startswith("{"):
        parsed = ast.literal_eval(stripped)
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected a dict literal, got: {value!r}")
        return parsed

    items: Dict = {}
    for pair in value.split(","):
        pair = pair.strip()
        if not pair:
            continue
        key, separator, item = pair.partition("=")
        if not separator:
            continue
        items[key.strip()] = item.strip()
    return items


class Env:
    """Reads and casts environment variables.

    On construction the process environment is captured; ``read_env`` layers a
    dotenv file on top. Typed accessors (``str``, ``int``, ``bool`` ...) cast the
    raw value; a variable holding the literal ``none`` reads back as None.
    """

    BOOLEAN_TRUE_VALUES = frozenset({"1", "y", "yes", "true", "on"})
    NONE_VALUE = "none"

    def __init__(self) -> None:
        """Capture the current process environment."""
        self._envs: dict[str, str] = {}
        self._envs.update(os.environ)

    def __contains__(self, variable: Str) -> Bool:
        """Return whether ``variable`` is set."""
        return variable in self._envs

    def read_env(self, env_file: Path | str, override: Bool = False):
        """Load variables from a dotenv file into this instance.

        Blank lines and ``#`` comments are skipped; each ``key=value`` line has
        surrounding quotes and whitespace stripped from the value.

        Args:
            env_file: Path to the dotenv file.
            override: When True, replace variables already present; otherwise
                keep the existing value.

        Raises:
            ValueError: The file does not exist.
            TypeError: The path is not a regular file.
        """
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
            value = value.strip(" \"'")

            if override or variable not in self._envs:
                self._envs[variable] = value

    def get_value(
        self,
        variable: Str,
        default: Any | EllipsisType | None = ...,
        cast: Callable[[Any], Any] = lambda v: v,
    ) -> Any | None:
        """Look up an environment variable and cast its value.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing; if omitted, a
                missing variable raises instead.
            cast: Callable applied to the raw Str value before returning.

        Returns:
            The cast value; None when the variable holds the ``none`` value;
            otherwise ``default`` or None when the variable is missing.

        Raises:
            EnvironmentNotFoundError: The variable is missing and no ``default`` was provided.
        """
        value = self._envs.get(variable)
        if value is not None:
            if value.lower() == self.NONE_VALUE:
                return None
            return cast(value)
        elif default is not ...:
            return default
        else:
            raise EnvironmentNotFoundError(f"Not found environment: {variable}.")

    def str(self, variable: Str, default: Str | EllipsisType = ...) -> Str | None:
        """Read an environment variable as a str.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.

        Returns:
            The Str value, or None when the variable holds the ``none`` value.
        """
        return self.get_value(variable, default, str)

    def int(self, variable: Str, default: Int | EllipsisType = ...) -> Int | None:
        """Read an environment variable as an int.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.

        Returns:
            The int value, or None when the variable holds the ``none`` value.
        """
        return self.get_value(variable, default, int)

    def float(self, variable: Str, default: Float | EllipsisType = ...) -> Float | None:
        """Read an environment variable as a float.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.

        Returns:
            The float value, or None when the variable holds the ``none`` value.
        """
        return self.get_value(variable, default, float)

    def bool(self, variable: Str, default: Bool | EllipsisType = ...) -> Bool | None:
        """Read an environment variable as a bool.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.

        Returns:
            True when the raw value is one of ``BOOLEAN_TRUE_VALUES``; None when the
            variable holds the ``none`` value.
        """
        cast = lambda v: v.lower() in self.BOOLEAN_TRUE_VALUES
        return self.get_value(variable, default, cast)

    def list(
        self, variable: Str, default: List | EllipsisType = ..., split: Str = ","
    ) -> List | None:
        """Read an environment variable as a delimited list of Strs.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.
            split: Delimiter used to split the raw value.

        Returns:
            The list of stripped items, or None when the variable holds the ``none`` value.
        """
        cast = lambda v: [s.strip() for s in v.strip().split(split)]
        return self.get_value(variable, default, cast)

    def dict(self, variable: Str, default: Dict | EllipsisType = ...) -> Dict | None:
        """Read an environment variable as a dict.

        The raw value is either a comma-separated list of ``key=value`` pairs
        (``"a=1,b=2"``) or a Python/JSON dict literal (``"{'a': '1', 'b': 2}"``).

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.

        Returns:
            The parsed dict, or None when the variable holds the ``none`` value.
        """
        return self.get_value(variable, default, _to_dict)

    def dns(
        self,
        provider: Str,
        host: Str,
        port: Str,
        user: Str,
        password: Str,
        name: Str,
        default: Str | EllipsisType = ...,
    ) -> Str | None:
        """Assemble a DSN connection Str from environment variables.

        Args:
            provider: URL scheme, e.g. ``postgres`` or ``redis``.
            host: Name of the env var holding the host.
            port: Name of the env var holding the port.
            user: Name of the env var holding the user; blank when unset.
            password: Name of the env var holding the password; blank when unset.
            name: Name of the env var holding the database name.
            default: Value returned when a required var is missing.

        Returns:
            The ``provider://user:password@host:port/name`` Str, or ``default``
            when a required var is missing.

        Raises:
            EnvironmentNotFoundError: A required var is missing and no ``default`` was provided.
        """
        try:
            host_value = self.str(host)
            port_value = self.int(port)
            name_value = self.str(name)
            user = self.str(user, "") or ""
            password = self.str(password, "") or ""

        except EnvironmentNotFoundError:
            if default is not ...:
                return default
            raise
        else:
            credential = f"{user}:{password}@" if user or password else ""
            return f"{provider}://{credential}{host_value}:{port_value}/{name_value}"

    def time(self, variable: Str, default: Float | EllipsisType = ...) -> Float | None:
        """Read an environment variable as a duration in seconds.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.

        Returns:
            The duration in seconds, or None when the variable holds the ``none`` value.
        """
        return self.get_value(variable, default, humanize.to_time)

    def byte_size(self, variable: Str, default: Int | EllipsisType = ...) -> Int | None:
        """Read an environment variable as a byte size.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.

        Returns:
            The size in bytes, or None when the variable holds the ``none`` value.
        """
        return self.get_value(variable, default, humanize.to_byte_size)

    def path(self, variable: Str, default: Path | EllipsisType = ...) -> Path | None:
        """Read an environment variable as a filesystem path.

        Args:
            variable: Name of the environment variable to read.
            default: Value returned when the variable is missing.

        Returns:
            The path, or None when the variable holds the ``none`` value.
        """
        return self.get_value(variable, default, Path)

    def secret(self, variable: Str) -> Str:
        """Read a required secret environment variable.

        Unlike ``str``, this never accepts a default: secrets must always be set
        explicitly. The raw value is stripped of surrounding whitespace and
        rejected if that leaves it empty, so a blank or whitespace-only secret
        fails startup the same way an absent one does.

        Args:
            variable: Name of the environment variable to read.

        Returns:
            The stripped Str value.

        Raises:
            EnvironmentNotFoundError: The variable is absent from the environment.
            EnvironmentBlankError: The variable is present but empty or
                whitespace-only after stripping.
        """
        value = (self.str(variable) or "").strip()
        if not value:
            raise EnvironmentBlankError(f"Environment variable {variable} must not be blank.")
        return value
