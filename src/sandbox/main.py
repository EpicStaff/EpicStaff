import asyncio
import json
import os
import shutil
from src.shared.models import CodeResultData, CodeTaskData
from src.shared.redis_streams import RedisStreamClient

from services.redis_service import RedisService
from services.storage_credential_client import StorageCredentialClient
from dynamic_venv_executor_chain import DynamicVenvExecutorChain
import isolation
import landlock
from utils.logger import logger

import settings


# Deliberately no STORAGE_ACCESS_KEY/STORAGE_SECRET_KEY here:
# sandbox no longer holds any static MinIO credential. Temporary,
# per-execution credentials are requested from the issuer running in
# django_app -- see StorageCredentialClient / dynamic_venv_executor_chain.py.
storage_credential_request_stream_client = RedisStreamClient(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    password=settings.REDIS_PASSWORD,
)
storage_credential_client = StorageCredentialClient(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    password=settings.REDIS_PASSWORD,
    stream_client=storage_credential_request_stream_client,
)
executor_chain = DynamicVenvExecutorChain(
    output_path=settings.OUTPUT_PATH,
    base_venv_path=settings.BASE_VENV_PATH,
    storage_credential_client=storage_credential_client,
)
redis_service = RedisService(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    user=settings.REDIS_USER,
    password=settings.REDIS_PASSWORD,
)

os.chdir("savefiles")


def sweep_output_path():
    """
    Clean up orphan execution folders left over from past executions
    """
    if not settings.OUTPUT_PATH.exists():
        settings.OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output path '{settings.OUTPUT_PATH}' did not exist, created it.")
        return

    removed = 0
    for entry in settings.OUTPUT_PATH.iterdir():
        if not entry.is_dir():
            continue
        try:
            shutil.rmtree(entry)
            removed += 1
        except Exception as e:
            logger.warning(f"Failed to remove orphan execution folder '{entry}': {e}")

    logger.info(
        f"Startup sweep: removed {removed} orphan execution folder(s) from '{settings.OUTPUT_PATH}'."
    )


def log_secret_masking_state():
    """Announce the MASK_SECRET setting once per process."""
    if settings.MASK_SECRET:
        logger.info("Secret masking is ON: secret values are redacted from output.")
    else:
        logger.warning(
            "Secret masking is OFF (SANDBOX_MASK_SECRET=false): plaintext secret values will appear "
            "in stdout, stderr, execution results and these logs. Do not use this "
            "with real credentials."
        )


def log_isolation_state():
    """Announce the Landlock filesystem-jail state once per process."""
    abi = landlock.abi_version()
    if abi >= 1:
        logger.info(
            "Filesystem isolation is ON: Landlock ABI {} enforced per execution.", abi
        )
    elif isolation.isolation_required():
        logger.warning(
            "Filesystem isolation is UNAVAILABLE (kernel lacks Landlock) and "
            "{} is not false: executions will be refused until this is resolved.",
            isolation.REQUIRE_ISOLATION_ENV_VAR,
        )
    else:
        logger.warning(
            "Filesystem isolation is UNAVAILABLE (kernel lacks Landlock) and "
            "{}=false: executions will run UNCONFINED. Do not use this in "
            "production.",
            isolation.REQUIRE_ISOLATION_ENV_VAR,
        )


async def init():
    sweep_output_path()
    log_secret_masking_state()
    log_isolation_state()
    await redis_service.connect()
    await storage_credential_request_stream_client.connect()


async def listen_redis():
    logger.info(
        f"Subscribed to channel '{settings.CODE_EXEC_CHANNEL}' for code execution tasks."
    )

    while True:
        try:
            pubsub = await redis_service.async_subscribe(settings.CODE_EXEC_CHANNEL)
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        code_task_data = CodeTaskData(**data)
                        # Never log message["data"]: it carries resolved secret
                        # plaintext. log_summary() is the safe projection.
                        logger.info(
                            "Received code execution task: {}",
                            code_task_data.log_summary(),
                        )
                        asyncio.create_task(run(code_task_data=code_task_data))
                    except Exception as e:
                        logger.error("Error processing message: {}", e)
        except Exception as e:
            logger.error("Redis listener disconnected, reconnecting in 1s: {}", e)
            await asyncio.sleep(1)


async def run(code_task_data: CodeTaskData):
    """
    Run the dynamic virtual environment execution chain.
    """
    execution_dir = settings.OUTPUT_PATH / code_task_data.execution_id
    try:
        try:
            result = await executor_chain.run(
                venv_name=code_task_data.venv_name,
                libraries=code_task_data.libraries,
                code=code_task_data.code,
                execution_id=code_task_data.execution_id,
                entrypoint=code_task_data.entrypoint,
                func_kwargs=code_task_data.func_kwargs,
                global_kwargs=code_task_data.global_kwargs,
                use_storage=code_task_data.use_storage,
                storage_allowed_paths=code_task_data.storage_allowed_paths,
                storage_org_prefix=code_task_data.storage_org_prefix,
                secrets=code_task_data.secrets,
            )
        except Exception as e:
            # executor_chain.run() is already expected to fail closed and
            # return an error CodeResultData rather than raise (see
            # dynamic_venv_executor_chain.py). This is defense in depth: if
            # something still escapes uncaught, we must still publish a
            # code_results message so callers waiting on this execution_id
            # don't hang, and so any temporary storage credential minted for
            # it is revoked by django_app's result_listener.
            logger.exception(
                "Unhandled exception running execution chain (execution_id={})",
                code_task_data.execution_id,
            )
            await redis_service.async_publish(
                channel=settings.CODE_RESULT_CHANNEL,
                message=CodeResultData(
                    execution_id=code_task_data.execution_id,
                    stderr=f"Unhandled exception running execution chain: {e}",
                    stdout="",
                    returncode=1,
                ).model_dump(),
            )
            return

        if code_task_data.use_storage and code_task_data.storage_org_prefix:
            try:
                mutations_path = (
                    settings.OUTPUT_PATH
                    / code_task_data.execution_id
                    / "storage_mutations.json"
                )

                if mutations_path.exists():
                    with open(mutations_path, "r") as f:
                        mutations = json.load(f)

                    if mutations:
                        event = {
                            "execution_id": code_task_data.execution_id,
                            "org_prefix": code_task_data.storage_org_prefix,
                            "session_id": code_task_data.session_id,
                            "mutations": mutations,
                        }
                        await redis_service.async_publish(
                            channel=settings.STORAGE_MUTATION_CHANNEL, message=event
                        )
            except Exception as e:
                logger.warning(f"Failed to publish storage mutations: {e}")

        await redis_service.async_publish(
            channel=settings.CODE_RESULT_CHANNEL, message=result.model_dump()
        )

    finally:
        if execution_dir.exists():
            try:
                shutil.rmtree(execution_dir)
            except Exception as e:
                logger.warning(f"Failed to cleanup {execution_dir}: {e}")


if __name__ == "__main__":
    asyncio.run(init())
    asyncio.run(listen_redis())
