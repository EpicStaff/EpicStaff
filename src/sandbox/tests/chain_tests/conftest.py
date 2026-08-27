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

    src_mod.shared = src_shared_mod
    src_shared_mod.models = src_shared_models_mod

    sys.modules.setdefault("src", src_mod)
    sys.modules.setdefault("src.shared", src_shared_mod)
    sys.modules.setdefault("src.shared.models", src_shared_models_mod)


_ensure_src_shared_stub()
