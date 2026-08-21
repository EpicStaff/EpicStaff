from __future__ import annotations
from abc import ABC, abstractmethod
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List
from secret_scrubber import masking_enabled, scrub
from src.shared.models import CodeResultData
from services.storage_credential_manager import StorageCredentialManager
from utils.environment import build_base_env
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
        predefined_libraries = {
            "/app/src/shared/dotdict",
            "/app/src/shared/epicstaff_secrets",
        }  # TODO: deal with hard coded path
        if context.get("use_storage"):
            predefined_libraries.add("/app/src/shared/epicstaff_storage")
        context["libraries"].update(predefined_libraries)

        context["libraries"] = sorted(context["libraries"])
        lib_hash = self.calculate_hash(context["libraries"])
        base_venv_path = context.get("base_venv_path")
        venv_path: Path = Path(base_venv_path) / Path(lib_hash)
        python_executable = (
            venv_path / Path("bin/python")
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

            env = build_base_env(python_executable)

            # Upgrade pip
            process = await asyncio.create_subprocess_exec(
                str(python_executable), "-m", "pip", "install", "--upgrade", "pip",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )  # fmt: off
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
            process = await asyncio.create_subprocess_exec(
                str(python_executable), "-m", "pip", "freeze",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )  # fmt: off
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
                process = await asyncio.create_subprocess_exec(
                    str(python_executable), "-m", "pip", "uninstall", "-y", package_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )  # fmt: off
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

            # Install libraries
            for library in context["libraries"]:
                logger.info(f"Installing {library}...")
                process = await asyncio.create_subprocess_exec(
                    str(python_executable), "-m", "pip", "install", "--", library,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )  # fmt: off
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
        storage_mutations_path: Path | None = None,
    ):
        global_kwargs = global_kwargs or dict()
        code_lines = code.split("\n")
        code_lines = ["    " + line for line in code_lines]
        code = "\n".join(code_lines)
        wrapped_code = f"""
import sys
import json

try:
    from dotdict import DotDict, DotObject, DotList
    from epicstaff_secrets import get_secret
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
"""

        if storage_mutations_path:
            wrapped_code += f"""
try:
    from epicstaff_storage.storage import get_mutations as __es_get_muts
    import json as __es_json
    __es_muts = __es_get_muts()
    if __es_muts:
        with open(r'{storage_mutations_path.as_posix()}', 'w') as __es_mf:
            __es_json.dump(__es_muts, __es_mf)
except Exception:
    pass
"""

        wrapped_code += "sys.exit(0)\n"

        return wrapped_code

    async def handle(self, context: Dict[str, Any]) -> Any:
        """Execute the provided code asynchronously."""
        python_executable = context["python_executable"]

        temp_code_path = context["temp_code_path"]

        storage_mutations_path = None
        if context.get("use_storage"):
            storage_mutations_path = (
                Path(context["result_file_path"]).parent / "storage_mutations.json"
            )

        wrapped_code = self.wrap_code(
            code=context["code"],
            result_file_path=context["result_file_path"],
            entrypoint=context["entrypoint"],
            func_kwargs=context["func_kwargs"],
            global_kwargs=context["global_kwargs"],
            storage_mutations_path=storage_mutations_path,
        )

        # Write the code to a temporary file
        with open(temp_code_path, "w") as f:
            f.write(wrapped_code)

        # Execute the code asynchronously
        logger.info("Executing code using {}...", python_executable)
        env = build_base_env(context["python_executable"])
        env["HOME"] = context["home_path"]
        if context.get("use_storage"):
            env["STORAGE_ENDPOINT"] = os.environ["STORAGE_ENDPOINT"]
            env["STORAGE_BUCKET_NAME"] = os.environ["STORAGE_BUCKET_NAME"]
            env["STORAGE_ACCESS_KEY"] = context["temp_storage_access_key"]
            env["STORAGE_SECRET_KEY"] = context["temp_storage_secret_key"]
        if (storage_allowed_paths := context.get("storage_allowed_paths")) is not None:
            env["STORAGE_ALLOWED_PATHS"] = json.dumps(storage_allowed_paths)
        if (storage_org_prefix := context.get("storage_org_prefix")) is not None:
            env["STORAGE_ORG_PREFIX"] = storage_org_prefix
        if (secrets := context.get("secrets")) is not None:
            env["EPICSTAFF_SECRETS"] = json.dumps(secrets)

        process = await asyncio.create_subprocess_exec(
            str(python_executable),
            str(temp_code_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await process.communicate()
        stderr = stderr.decode("utf-8", errors="replace")
        stdout = stdout.decode("utf-8", errors="replace")
        returncode = process.returncode

        secrets = context.get("secrets") or {}
        mask_secrets = masking_enabled()
        if mask_secrets:
            stderr = scrub(text=stderr, secrets=secrets)
            stdout = scrub(text=stdout, secrets=secrets)

        if stderr:
            logger.info("Error: {}", stderr)

        result_file_path: Path | str = context["result_file_path"]
        if isinstance(result_file_path, Path):
            result_file_path = result_file_path.as_posix()

        result_data = None

        if returncode == 0:
            try:
                with open(result_file_path, "r", encoding="utf-8") as file:
                    raw_result = file.read()
                result_data = (
                    scrub(text=raw_result, secrets=secrets)
                    if mask_secrets
                    else raw_result
                )
            except Exception:
                logger.exception("Exception reading result file")

        if self._next_handler:
            return await super().handle(context)

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
        storage_credential_manager: StorageCredentialManager,
    ):
        self.output_path = output_path
        self.base_venv_path = base_venv_path
        self.storage_credential_manager = storage_credential_manager

        # Build the chain of responsibility
        create_venv_handler = CreateVenvHandler()
        install_libraries_handler = InstallLibrariesHandler()
        execute_code_handler = ExecuteCodeHandler()

        self.chain: Handler = DummyHandler()

        (
            self.chain
            .set_next(create_venv_handler)
            .set_next(install_libraries_handler)
            .set_next(execute_code_handler)
        )  # fmt: off

    async def run(
        self,
        libraries: list[str],
        venv_name: str,
        execution_id: str,
        code: str,
        entrypoint: str = "main",
        func_kwargs: dict[str, Any] | None = None,
        global_kwargs: dict[str, Any] | None = None,
        use_storage: bool = False,
        storage_allowed_paths: list[str] | None = None,
        storage_org_prefix: str | None = None,
        secrets: dict[str, str] | None = None,
    ) -> CodeResultData:
        """Run the complete workflow asynchronously."""
        if func_kwargs is None:
            func_kwargs = dict()

        output_path = Path(self.output_path) / execution_id
        os.makedirs(output_path, exist_ok=True)
        os.makedirs(self.base_venv_path, exist_ok=True)
        home_path = output_path / "home"
        os.makedirs(home_path, exist_ok=True)

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
            "home_path": str(home_path),
            "use_storage": use_storage,
            "storage_allowed_paths": storage_allowed_paths,
            "storage_org_prefix": storage_org_prefix,
            "secrets": secrets,
        }
        temp_access_key: str | None = None
        if use_storage:
            try:
                policy = self.storage_credential_manager.build_policy(
                    allowed_bucket=os.environ["STORAGE_BUCKET_NAME"],
                    allowed_folders=self._scoped_folders(
                        storage_org_prefix, storage_allowed_paths
                    ),
                )
                temp_access_key, temp_secret_key = (
                    await self.storage_credential_manager.create(policy)
                )
            except Exception as e:
                logger.error("Failed to provision scoped storage credentials: {}", e)
                return CodeResultData(
                    execution_id=execution_id,
                    stderr=f"Failed to provision scoped storage credentials: {e}",
                    stdout="",
                    returncode=1,
                )
            context["temp_storage_access_key"] = temp_access_key
            context["temp_storage_secret_key"] = temp_secret_key

        try:
            result = await self.chain.handle(context)
        finally:
            if temp_access_key is not None:
                await self.storage_credential_manager.revoke(temp_access_key)

        logger.info(result)
        return result

    @staticmethod
    def _scoped_folders(org_prefix: str | None, allowed_paths: list[str] | None) -> set[str]:
        if not org_prefix:
            raise ValueError("storage_org_prefix is required when use_storage is set")
        if not allowed_paths:
            return {f"{org_prefix}/"}  # whole org (folder)
        return {f"{org_prefix}/{path.lstrip('/')}" for path in allowed_paths}