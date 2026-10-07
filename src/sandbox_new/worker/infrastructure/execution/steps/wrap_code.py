"""Renders the execution's wrapped source and writes it to the code file."""

from worker.application.context import ExecutionContext
from worker.infrastructure.execution.code_wrapper import wrap_code

__all__ = ["WrapCodeStep"]


class WrapCodeStep:
    async def __call__(self, context: ExecutionContext) -> None:
        job = context.job
        source = wrap_code(
            code=job.code,
            result_file_path=context.result_file_path,
            entrypoint=job.entrypoint,
            func_kwargs=job.func_kwargs,
            global_kwargs=job.global_kwargs,
            storage_mutations_path=context.storage_mutations_path,
        )
        context.code_path.write_text(source, encoding="utf-8")
