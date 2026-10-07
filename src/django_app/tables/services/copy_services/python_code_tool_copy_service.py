from django.db import transaction
from django.db.models import Q
from rbac.authorship import record_last_edit, resolve_author
from tables.import_export.utils import clean_base_name, ensure_unique_identifier
from tables.models import Label
from tables.models.python_models import PythonCodeTool
from tables.serializers.utils.description_sanitizer import sanitize_description
from tables.services.copy_services.base_copy_service import BaseCopyService
from tables.services.copy_services.helpers import copy_python_code, next_copy_name


class PythonCodeToolCopyService(BaseCopyService):
    def copy(
        self,
        tool: PythonCodeTool,
        name: str | None = None,
        org_id: int | None = None,
        user=None,
    ) -> PythonCodeTool:
        target_org_id = org_id if org_id is not None else tool.org_id
        base_name = name if name else tool.name

        with transaction.atomic():
            new_name = next_copy_name(
                PythonCodeTool,
                org_id=target_org_id,
                base_name=base_name,
                also_taken=Q(built_in=True),
            )
            new_code = copy_python_code(tool.python_code)

            new_tool = PythonCodeTool.objects.create(
                name=new_name,
                description=sanitize_description(tool.description),
                variables=tool.variables,
                python_code=new_code,
                org_id=target_org_id,
                created_by=resolve_author(user),
            )
            record_last_edit(new_tool, user)

        new_tool.labels.set(tool.labels.filter(scope=Label.Scope.TOOL, org_id=target_org_id))
        return new_tool
