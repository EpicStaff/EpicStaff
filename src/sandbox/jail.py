"""Defines the filesystem allowlist a sandboxed execution is confined to.

This module is a pure allowlist builder: no I/O, no environment reads, no
filesystem checks. `launcher.py` applies this allowlist as a Landlock
ruleset around the child process before it runs untrusted code. Widening
any of the lists below is a security-relevant change and requires review.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Jail:
    read_write: tuple[str, ...]
    read_only: tuple[str, ...]
    read_exec: tuple[str, ...]


def build_jail(*, exec_dir: Path, venv_path: Path, savefiles_root: Path) -> Jail:
    read_write = (
        str(exec_dir.absolute()),
        str((exec_dir / "home").absolute()),
        str((exec_dir / "tmp").absolute()),
        str(savefiles_root.absolute()),
    )
    read_exec = (
        str(venv_path.absolute()),
        "/usr",
        "/lib",
        "/lib64",
        "/bin",
    )
    read_only = (
        "/etc/ld.so.cache",
        "/etc/ssl",
        "/etc/resolv.conf",
        "/etc/hosts",
        "/etc/nsswitch.conf",
        "/etc/localtime",
        "/dev/null",
        "/dev/zero",
        "/dev/urandom",
        "/dev/random",
    )
    return Jail(read_write=read_write, read_only=read_only, read_exec=read_exec)
