import asyncio
import json
import os
from pathlib import Path
from src.shared.models import CodeTaskData
from services.redis_service import RedisService
from dynamic_venv_executor_chain import DynamicVenvExecutorChain
from utils.logger import logger


redis_host = os.environ.get("REDIS_HOST", "127.0.0.1")
redis_port = int(os.environ.get("REDIS_PORT", "6379"))
redis_password = os.getenv("REDIS_PASSWORD")
code_result_channel = os.environ.get("CODE_RESULT_CHANNEL", "code_results")
storage_mutation_channel = os.environ.get(
    "STORAGE_MUTATION_CHANNEL", "storage_mutations"
)
task_channel = os.environ.get("CODE_EXEC_TASK_CHANNEL", "code_exec_tasks")
output_path = Path(os.environ.get("OUTPUT_PATH", "executions"))
base_venv_path = Path(os.environ.get("BASE_VENV_PATH", "venvs"))
executor_chain = DynamicVenvExecutorChain(
    output_path=output_path,
    base_venv_path=base_venv_path,
)
os.chdir("savefiles")

redis_service = RedisService(host=redis_host, port=redis_port, password=redis_password)


async def init():
    await redis_service.connect()


async def listen_redis():
    logger.info(f"Subscribed to channel '{task_channel}' for code execution tasks.")

    pubsub = await redis_service.async_subscribe(task_channel)

    async for message in pubsub.listen():
        if message["type"] == "message":
            try:
                logger.info(f"Received message: {message['data']}")

                data = json.loads(message["data"])
                code_task_data = CodeTaskData(**data)

                asyncio.create_task(run(code_task_data=code_task_data))

            except Exception as e:
                logger.error(f"Error processing message: {e}")


async def run(code_task_data: CodeTaskData):
    """
    Run the dynamic virtual environment execution chain.
    """

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
    )
    if code_task_data.use_storage and code_task_data.storage_org_prefix:
        try:
            mutations_path = (
                output_path / code_task_data.execution_id / "storage_mutations.json"
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
                        channel=storage_mutation_channel, message=event
                    )
        except Exception as e:
            logger.warning(f"Failed to publish storage mutations: {e}")

    await redis_service.async_publish(
        channel=code_result_channel, message=result.model_dump()
    )


if __name__ == "__main__":
    asyncio.run(init())
    asyncio.run(listen_redis())
