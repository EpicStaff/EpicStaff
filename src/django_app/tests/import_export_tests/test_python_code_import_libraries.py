"""The import boundary applies the same library rule as the runtime serializer.

`PythonCode.libraries` reaches `pip install` inside the sandbox, so a crafted
export file must not be able to smuggle a VCS URL, a direct `name @ url`
reference or a file path past import.
"""

import pytest
from rest_framework.exceptions import ValidationError

from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.python_tools import PythonCodeImportSerializer
from tables.import_export.strategies.nodes.python_node import PythonNodeStrategy
from tables.models import PythonCode

REJECTED_LIBRARIES = [
    "git+https://evil.example.com/x",
    "pkg@https://evil.example.com/y.whl",
    "requests git+https://evil.example.com/x",
    "file:///etc/passwd",
    "/etc/passwd",
    "./local-package",
    "-r requirements.txt",
]


def _python_code_payload(libraries: str) -> dict:
    return {
        "code": "def main(**kwargs):\n    return 1\n",
        "entrypoint": "main",
        "libraries": libraries,
        "global_kwargs": {},
    }


@pytest.mark.django_db
class TestPythonCodeImportSerializerLibraries:
    @pytest.mark.parametrize("libraries", REJECTED_LIBRARIES)
    def test_rejects_non_index_requirements(self, libraries):
        serializer = PythonCodeImportSerializer(data=_python_code_payload(libraries))

        assert not serializer.is_valid()
        assert "libraries" in serializer.errors

    def test_accepts_plain_index_requirements(self):
        serializer = PythonCodeImportSerializer(
            data=_python_code_payload("requests==2.31.0 numpy>=1,<2")
        )

        assert serializer.is_valid(), serializer.errors
        python_code = serializer.save()

        python_code.refresh_from_db()
        assert python_code.libraries == "requests==2.31.0 numpy>=1,<2"

    def test_accepts_blank_libraries(self):
        serializer = PythonCodeImportSerializer(data=_python_code_payload(""))

        assert serializer.is_valid(), serializer.errors
        assert serializer.save().libraries == ""


@pytest.mark.django_db
class TestPythonNodeImportRejectsVcsLibrary:
    def test_import_strategy_rejects_vcs_url_and_stores_nothing(self):
        strategy = PythonNodeStrategy()
        data = {
            "graph": 1,
            "python_code": _python_code_payload("git+https://evil.example.com/x"),
        }

        with pytest.raises(ValidationError) as error:
            strategy.create_entity(data, IDMapper())

        assert "libraries" in error.value.detail
        assert not PythonCode.objects.exists()
