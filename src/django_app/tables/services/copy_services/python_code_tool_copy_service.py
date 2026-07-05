from tables.import_export.utils import ensure_unique_identifier
from tables.models.python_models import PythonCodeTool
from tables.services.copy_services.base_copy_service import BaseCopyService
from tables.services.copy_services.helpers import copy_python_code


class PythonCodeToolCopyService(BaseCopyService):
    def copy(self, tool: PythonCodeTool, name: str | None = None) -> PythonCodeTool:
        if tool.built_in:
            raise ValueError("Cannot copy a built-in tool.")

        new_code = copy_python_code(tool.python_code)

        existing_names = PythonCodeTool.objects.values_list("name", flat=True)
        new_name = ensure_unique_identifier(
            base_name=name if name else tool.name,
            existing_names=existing_names,
        )

        return PythonCodeTool.objects.create(
            name=new_name,
            description=tool.description,
            variables=tool.variables,
            python_code=new_code,
            favorite=tool.favorite,
        )
