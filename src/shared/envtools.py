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
        default: Any = ...,
        cast: Callable[[Any], Any]=lambda v: v,
    ):
        value = self._envs.get(variable)
        if value is not None:
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
        default: str | EllipsisType = ...
    ) -> str:
        try:
            host = self.str(host)
            port = self.int(port)
            user = self.str(user, "")
            password = self.str(password, "")
        except EnvironmentNotFoundError:
            if default is not ...:
                return default
            raise
        else:
            credential = f"{user}:{password}@" if user or password else ""
            return f"{provider}://{credential}{host}:{port}"

    def time(self, variable: str, default: float | EllipsisType = ...) -> float:
        return self.get_value(variable, default, humanize.to_time)

    def byte_size(self, variable: str, default: int | EllipsisType = ...) -> int:
        return self.get_value(variable, default, humanize.to_byte_size)

    def path(self, variable: str, default: Path | EllipsisType = ...) -> Path:
        return self.get_value(variable, default, Path)

    def list(self, variable: str, default: list | EllipsisType = ..., split=",") -> list:
        cast = lambda v: [s.strip() for s in v.strip().split(split)]
        return self.get_value(variable, default, cast)

    def int(self, variable: str, default: int | EllipsisType = ...) -> int:
        return self.get_value(variable, default, int)

    def float(self, variable: str, default: float | EllipsisType = ...) -> float:
        return self.get_value(variable, default, float)

    def bool(self, variable: str, default: bool | EllipsisType = ...) -> bool:
        cast = lambda v: v.lower() in self.BOOLEAN_TRUE_VALUES
        return self.get_value(variable, default, cast)

    def str(self, variable: str, default: str | EllipsisType = ...) -> str:
        return self.get_value(variable, default, str)