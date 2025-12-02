from __future__ import annotations
from abc import ABC, abstractmethod
import asyncio
from asyncio.subprocess import Process
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from models import CodeResultData
from services.redis_service import RedisService
from utils.logger import logger


class Handler(ABC):
    """
    The Handler interface declares a method for building the chain of handlers.
    It also declares a method for executing a request.
    """

    @abstractmethod
    def set_next(self, handler: Handler) -> Handler:
        pass

    @abstractmethod
    async def handle(self, context: Dict[str, Any]) -> Any:
        pass


class AbstractHandler(Handler):
    """
    The default chaining behavior can be implemented inside a base handler
    class.
    """

    _next_handler: Handler = None

    def set_next(self, handler: Handler) -> Handler:
        self._next_handler = handler
        return handler

    @abstractmethod
    async def handle(self, context: Dict[str, Any]) -> Any:
        if self._next_handler:
            return await self._next_handler.handle(context)

        return None


class DummyHandler(AbstractHandler):
    async def handle(self, context):
        return await super().handle(context)


class CreateVenvHandler(AbstractHandler):

    def calculate_hash(self, libraries: List[str]) -> str:
        """Calculate a hash of the libraries list."""
        libraries_str = json.dumps(libraries, sort_keys=True)
        return hashlib.sha256(libraries_str.encode("utf-8")).hexdigest()

    async def handle(self, context: Dict[str, Any]) -> Any:
        """Create virtual environment task."""

        context["libraries"] = set(context["libraries"])
        # Install libraries
        predefined_libraries = {"/home/user/root/app/shared/dotdict"}
        context["libraries"].update(predefined_libraries)

        context["libraries"] = sorted(context["libraries"])
        lib_hash = self.calculate_hash(context["libraries"])
        base_venv_path = context.get("base_venv_path")
        venv_path: Path = Path(base_venv_path) / Path(lib_hash)
        python_executable = (
            venv_path / Path(f"bin/python")
            if os.name != "nt"
            else venv_path / Path("Scripts/python")
        )
        hash_file = venv_path / "libhash"
        context["venv_path"] = venv_path
        context["python_executable"] = python_executable
        context["hash_file"] = hash_file
        context["lib_hash"] = lib_hash

        if not venv_path.exists():
            logger.info(f"Creating virtual environment at {venv_path}...")
            process = await asyncio.create_subprocess_shell(
                f"{sys.executable} -m venv {venv_path}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()
        else:
            logger.info(f"Virtual environment already exists at {venv_path}.")

        if self._next_handler:
            return await super().handle(context)
        return "Virtual environment created."


class InstallLibrariesHandler(AbstractHandler):

    def calculate_hash(self, libraries: List[str]) -> str:
        """Calculate a hash of the libraries list."""
        libraries_str = json.dumps(libraries, sort_keys=True)
        return hashlib.sha256(libraries_str.encode("utf-8")).hexdigest()

    def _hash_changed(self, lib_hash: str, hash_file: Path) -> bool:
        """Check if the hash of the libraries has changed."""
        if hash_file.exists():
            with open(hash_file, "r") as f:
                saved_hash = f.read().strip()
            return lib_hash != saved_hash
        return True

    def _update_hash(self, lib_hash: str, hash_file: Path):
        """Update the hash file with the current hash."""
        with open(hash_file, "w") as f:
            f.write(lib_hash)

    async def handle(self, context: Dict[str, Any]) -> Any:
        """Install libraries asynchronously."""
        python_executable = context["python_executable"]
        lib_hash = context.get("lib_hash")
        hash_changed = self._hash_changed(
            lib_hash=lib_hash, hash_file=context["hash_file"]
        )

        if hash_changed:
            logger.info("Installing libraries...")

            # Upgrade pip
            process = await asyncio.create_subprocess_shell(
                f"{python_executable} -m pip install --upgrade pip",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            stderr = stderr.decode("utf-8", errors="replace")
            stdout = stdout.decode("utf-8", errors="replace")
            returncode = process.returncode

            if returncode != 0:
                return CodeResultData(
                    execution_id=context["execution_id"],
                    stderr=stderr,
                    stdout=stdout,
                    returncode=returncode,
                )

            # Uninstall all libraries
            logger.info("Uninstalling all libraries...")
            process = await asyncio.create_subprocess_shell(
                f"{python_executable} -m pip freeze",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            returncode = process.returncode

            stderr = stderr.decode("utf-8", errors="replace")
            stdout = stdout.decode("utf-8", errors="replace")
            if returncode != 0:
                return CodeResultData(
                    execution_id=context["execution_id"],
                    stderr=stderr,
                    stdout=stdout,
                    returncode=returncode,
                )

            installed_packages = stdout.splitlines()

            for package in installed_packages:
                package_name = package.split("==")[0]
                logger.info(f"Uninstalling {package_name}...")
                await asyncio.create_subprocess_shell(
                    f"{python_executable} -m pip uninstall -y {package_name}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()
                stderr = stderr.decode("utf-8", errors="replace")
                stdout = stdout.decode("utf-8", errors="replace")
                if returncode != 0:
                    return CodeResultData(
                        execution_id=context["execution_id"],
                        stderr=stderr,
                        stdout=stdout,
                        returncode=returncode,
                    )

            # Install libraries
            for library in context["libraries"]:
                logger.info(f"Installing {library}...")
                process = await asyncio.create_subprocess_shell(
                    f"{python_executable} -m pip install {library}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()
                stderr = stderr.decode("utf-8", errors="replace")
                stdout = stdout.decode("utf-8", errors="replace")
                returncode = process.returncode

                if returncode != 0:
                    return CodeResultData(
                        execution_id=context["execution_id"],
                        stderr=stderr,
                        stdout=stdout,
                        returncode=returncode,
                    )

            self._update_hash(lib_hash=lib_hash, hash_file=context["hash_file"])
        else:
            logger.info("Libraries are up-to-date. Skipping installation.")

        if self._next_handler:
            return await super().handle(context)
        return "Libraries installed."


class ExecuteCodeHandler(AbstractHandler):

    def wrap_code(
        self,
        code: str,
        result_file_path: Path,
        entrypoint: str,
        func_kwargs: dict[str, Any],
        global_kwargs: dict[str, Any] | None = None,
    ):
        global_kwargs = global_kwargs or dict()
        code_lines = code.split("\n")
        code_lines = ["    " + line for line in code_lines]
        code = "\n".join(code_lines)
        wrapped_code = f"""
import sys
import json
from dotdict import DotDict, DotObject, DotList
try:
    for k, v in {global_kwargs}.items():
        globals()[k] = v
    
{code}
    
    __sys_dot_kwargs = DotDict({func_kwargs})
    
    sys_result_variable = {entrypoint}(**__sys_dot_kwargs)
    with open(r'{result_file_path.as_posix()}', 'w', encoding='utf-8') as file:
        file.write(json.dumps(sys_result_variable))
except Exception as e:
    print(str(e), file=sys.stderr)
    sys.exit(1)
sys.exit(0)
"""

        return wrapped_code

    async def handle(self, context: Dict[str, Any]) -> Any:
        """Execute the provided code asynchronously."""
        python_executable = context["python_executable"]

        temp_code_path = context["temp_code_path"]

        wrapped_code = self.wrap_code(
            code=context["code"],
            result_file_path=context["result_file_path"],
            entrypoint=context["entrypoint"],
            func_kwargs=context["func_kwargs"],
            global_kwargs=context["global_kwargs"],
        )

        # Write the code to a temporary file
        with open(temp_code_path, "w") as f:
            f.write(wrapped_code)

        # Execute the code asynchronously
        logger.info(f"Executing code using {python_executable}...")
        process = await asyncio.create_subprocess_shell(
            f"{python_executable} {temp_code_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        stderr = stderr.decode("utf-8", errors="replace")
        stdout = stdout.decode("utf-8", errors="replace")
        returncode = process.returncode
        if stderr:
            logger.info(f"Error: {stderr}")

        result_file_path: Path | str = context["result_file_path"]
        if isinstance(result_file_path, Path):
            result_file_path = result_file_path.as_posix()

        result_data = None

        if returncode == 0:
            try:
                with open(result_file_path, "r", encoding="utf-8") as file:
                    result_data = file.read()
            except Exception:
                logger.exception("Exception reading result file")

        if self._next_handler:
            return super().handle(context)

        return CodeResultData(
            execution_id=context["execution_id"],
            result_data=result_data,
            stderr=stderr,
            stdout=stdout,
            returncode=returncode,
        )


class DynamicVenvExecutorChain:

    def __init__(
        self,
        output_path: str | Path,
        base_venv_path: str | Path,
    ):
        self.output_path = output_path
        self.base_venv_path = base_venv_path

        # Build the chain of responsibility
        create_venv_handler = CreateVenvHandler()
        install_libraries_handler = InstallLibrariesHandler()
        execute_code_handler = ExecuteCodeHandler()

        self.chain: Handler = DummyHandler()

        self.chain.set_next(create_venv_handler).set_next(
            install_libraries_handler
        ).set_next(execute_code_handler)

    async def run(
        self,
        libraries: list[str],
        venv_name: str,
        execution_id: str,
        code: str,
        entrypoint: str = "main",
        func_kwargs: dict[str, Any] | None = None,
        global_kwargs: dict[str, Any] | None = None,
    ) -> CodeResultData:
        """Run the complete workflow asynchronously."""
        if func_kwargs is None:
            func_kwargs = dict()

        output_path = Path(self.output_path) / execution_id
        os.makedirs(output_path, exist_ok=True)
        os.makedirs(self.base_venv_path, exist_ok=True)

        context = {
            "base_venv_path": self.base_venv_path,
            "libraries": libraries,
            "temp_code_path": output_path / "code.py",
            "code": code,
            "result_file_path": output_path / "output.txt",
            "entrypoint": entrypoint,
            "func_kwargs": func_kwargs,
            "execution_id": execution_id,
            "global_kwargs": global_kwargs,
        }

        result = await self.chain.handle(context)
        logger.info(result)
        return result
