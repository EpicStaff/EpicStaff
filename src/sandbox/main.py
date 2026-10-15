import asyncio
import json
import os
import shutil

import egress_firewall
import isolation
import landlock
import settings
from dynamic_venv_executor_chain import SANDBOX_UID, DynamicVenvExecutorChain
from network_policy import NetworkPolicy, decide_network_policy
from services.redis_service import RedisService
from services.storage_credential_manager import StorageCredentialManager
from signal_isolation_policy import SignalIsolationPolicy, decide_signal_isolation_policy
from src.shared.models import CodeTaskData
from utils.logger import logger

storage_credential_manager = StorageCredentialManager(
    host=settings.STORAGE_ENDPOINT,
    access_key=settings.STORAGE_ACCESS_KEY,
    secret_key=settings.STORAGE_SECRET_KEY,
)
executor_chain = DynamicVenvExecutorChain(
    output_path=settings.OUTPUT_PATH,
    base_venv_path=settings.BASE_VENV_PATH,
    storage_credential_manager=storage_credential_manager,
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
    """Announce the state of every isolation layer once per process."""

    # Filesystem isolation log
    abi = landlock.abi_version()
    if abi >= 1:
        logger.info("Filesystem isolation is ON: Landlock ABI {} enforced per execution.", abi)
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

    # Private-network isolation log
    carve_outs = egress_firewall.active_carve_outs()
    if not settings.BLOCK_PRIVATE_NETWORK:
        logger.warning(
            "Private-network isolation is OFF ({}=false): executions can reach the Docker "
            "host, the LAN, cloud metadata and other containers.",
            settings.BLOCK_PRIVATE_NETWORK_ENV_VAR,
        )
    elif carve_outs is not None:
        logger.info(
            "Private-network isolation is ON: executions cannot reach {} or non-loopback "
            "IPv6; allowed: DNS to {}, storage at {}.",
            ", ".join(egress_firewall.BLOCKED_IPV4_RANGES),
            ", ".join(carve_outs.nameservers) or "none",
            ", ".join(f"{ip}:{port}" for ip, port in carve_outs.storage_endpoints) or "none",
        )
    else:
        logger.error(
            "Private-network isolation is UNAVAILABLE (egress firewall not installed) and "
            "{} is not false: executions will be refused until this is resolved.",
            settings.BLOCK_PRIVATE_NETWORK_ENV_VAR,
        )

    # Network isolation log. Same decision the handler makes per execution;
    # only use_storage varies.
    storage_decision = decide_network_policy(
        block_network=True,
        use_storage=True,
        landlock_abi=abi,
        storage_port=int(settings.STORAGE_PORT),
    )
    if not settings.BLOCK_NETWORK:
        logger.warning(
            "Network isolation is OFF (SANDBOX_BLOCK_NETWORK=false): executions can open IP "
            "sockets to the internet; private addresses are governed by {}.",
            settings.BLOCK_PRIVATE_NETWORK_ENV_VAR,
        )
    elif storage_decision.policy is NetworkPolicy.ALLOW_PORTS:
        logger.info(
            "Network isolation is ON: executions cannot open IP sockets; storage-enabled "
            "executions may only connect over TCP to port {}.",
            settings.STORAGE_PORT,
        )
    else:
        logger.warning(
            "Network isolation is ON for executions without storage; storage-enabled "
            "executions will be refused (Landlock ABI {} < 4, needs Linux 6.7+).",
            abi,
        )

    # Signal isolation log
    signal_isolation_policy = decide_signal_isolation_policy(
        landlock_abi=abi, require_signal_isolation=settings.REQUIRE_SIGNAL_ISOLATION
    )
    if signal_isolation_policy is SignalIsolationPolicy.ENFORCE:
        logger.info(
            "Signal isolation is ON: Landlock blocks signals and abstract UNIX "
            "sockets from user code to anything outside its own execution."
        )
    elif signal_isolation_policy is SignalIsolationPolicy.REFUSE:
        logger.warning(
            "Signal isolation is UNAVAILABLE (Landlock ABI {} < 6, needs Linux 6.12+) and "
            "{} is not false: executions will be refused until this is resolved.",
            abi,
            settings.REQUIRE_SIGNAL_ISOLATION_ENV_VAR,
        )
    elif signal_isolation_policy is SignalIsolationPolicy.UNISOLATED:
        logger.warning(
            "Signal isolation is UNAVAILABLE (Landlock ABI {} < 6) and "
            "{}=false: executions can signal each other. Do not use this in production.",
            abi,
            settings.REQUIRE_SIGNAL_ISOLATION_ENV_VAR,
        )


async def init():
    sweep_output_path()
    log_secret_masking_state()
    if settings.BLOCK_PRIVATE_NETWORK:
        # Log and carry on rather than crash: a dead sandbox leaves every producer
        # waiting forever for a result, while ExecuteCodeHandler refuses each
        # execution with an explicit error.
        try:
            egress_firewall.apply(SANDBOX_UID)
        except egress_firewall.EgressFirewallUnavailableError as error:
            logger.error("Could not install the private-network egress firewall: {}", error)
    log_isolation_state()
    await redis_service.connect()


async def listen_redis():
    logger.info(f"Subscribed to channel '{settings.CODE_EXEC_CHANNEL}' for code execution tasks.")

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
                        asyncio.create_task(run(code_task_data=code_task_data))  # noqa: RUF006
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
        if code_task_data.use_storage and code_task_data.storage_org_prefix:
            try:
                mutations_path = (
                    settings.OUTPUT_PATH / code_task_data.execution_id / "storage_mutations.json"
                )

                if mutations_path.exists():
                    with open(mutations_path) as f:  # noqa: ASYNC230
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
