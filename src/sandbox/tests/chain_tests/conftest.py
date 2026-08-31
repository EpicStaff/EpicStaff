import sys
import types


def _ensure_src_shared_stub() -> None:
    if "src.shared.models" in sys.modules:
        return

    import dataclasses

    @dataclasses.dataclass
    class CodeResultData:
        execution_id: str
        result_data: str | None = None
        stderr: str = ""
        stdout: str = ""
        returncode: int = 0

    @dataclasses.dataclass
    class CodeTaskData:
        venv_name: str
        libraries: list
        code: str
        execution_id: str
        entrypoint: str
        func_kwargs: dict = dataclasses.field(default_factory=dict)
        global_kwargs: dict = dataclasses.field(default_factory=dict)
        secrets: dict = dataclasses.field(default_factory=dict)

    src_mod = types.ModuleType("src")
    src_shared_mod = types.ModuleType("src.shared")
    src_shared_models_mod = types.ModuleType("src.shared.models")

    src_shared_models_mod.CodeResultData = CodeResultData
    src_shared_models_mod.CodeTaskData = CodeTaskData

    class StreamEnvelope:
        def __init__(self, *, type, correlation_id, payload):
            self.type = type
            self.correlation_id = correlation_id
            self.payload = payload

        def to_fields(self) -> dict:
            return {
                "type": self.type,
                "correlation_id": self.correlation_id,
                "payload": self.payload,
            }

    class RedisStreamClient:
        """Import-time stand-in only: no test here exercises the real
        client's network behavior -- StorageCredentialClient is replaced by
        a fake in these tests, this just satisfies the module-level import
        in dynamic_venv_executor_chain.py -> storage_credential_client.py."""

        def __init__(self, *args, **kwargs):
            pass

    src_shared_redis_streams_mod = types.ModuleType("src.shared.redis_streams")
    src_shared_redis_streams_mod.RedisStreamClient = RedisStreamClient
    src_shared_redis_streams_mod.StreamEnvelope = StreamEnvelope

    src_mod.shared = src_shared_mod
    src_shared_mod.models = src_shared_models_mod
    src_shared_mod.redis_streams = src_shared_redis_streams_mod

    sys.modules.setdefault("src", src_mod)
    sys.modules.setdefault("src.shared", src_shared_mod)
    sys.modules.setdefault("src.shared.models", src_shared_models_mod)
    sys.modules.setdefault("src.shared.redis_streams", src_shared_redis_streams_mod)


_ensure_src_shared_stub()
