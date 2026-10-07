import asyncio
from pathlib import Path

from manager.application.ports import AbstractUVProvider
from manager.domain.types import LibraryString

__all__ = ["UVProvider"]


class UVProvider(AbstractUVProvider):
    PYTHON_VERSION = "3.12"

    @staticmethod
    async def run(
        *args: str,
        input=None,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    ):
        process = await asyncio.create_subprocess_exec(
            "uv",
            *args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )
        if input is not None:
            input = input.encode()
        _, error = await process.communicate(input)
        if process.returncode != 0:
            if stderr == asyncio.subprocess.PIPE:
                error = error.decode()
            raise RuntimeError(f"uv {' '.join(args)} failed:\n{error}")

    @classmethod
    async def init_venv(cls, venv_path: Path):
        if venv_path.exists():
            raise ValueError("Venv was inited yet.")
        await cls.run(
            "venv",
            "--no-config",
            "--no-progress",
            "--python",
            cls.PYTHON_VERSION,
            str(venv_path),
        )

    @classmethod
    async def apply(cls, venv_path: Path, *libs: LibraryString):
        if not venv_path.exists():
            raise ValueError(f"Venv is not initialized yet. Paht: {venv_path}")
        python_binary = cls.get_python_binary(venv_path)
        lock_file = cls.get_lock_file(venv_path)

        await cls.run(
            "pip",
            "compile",
            "--no-config",
            "--no-progress",
            "--generate-hashes",
            "--no-header",
            "--no-annotate",
            "--python",
            str(python_binary),
            "--output-file",
            str(lock_file),
            "-",
            input="\n".join(libs),
        )
        await cls.run(
            "pip",
            "sync",
            "--no-config",
            "--no-progress",
            "--python",
            str(python_binary),
            str(lock_file),
        )

    @classmethod
    async def install_local(cls, venv_path: Path, *packages: Path):
        # Local source packages are installed outside the compiled/hashed lock flow:
        # --generate-hashes cannot hash a directory. Installed straight into the venv.
        if not packages:
            return
        python_binary = cls.get_python_binary(venv_path)
        await cls.run(
            "pip",
            "install",
            "--no-config",
            "--no-progress",
            "--python",
            str(python_binary),
            *(str(package) for package in packages),
        )
