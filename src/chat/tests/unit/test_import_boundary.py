import re
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[2]
# src.shared is the cross-service contract every service imports; Django's code is not.
FORBIDDEN = re.compile(r"^\s*(from|import)\s+(src\.django_app|shared|django_app|django|tables|rbac)\b", re.M)


def test_service_imports_nothing_from_core():
    offenders = [
        str(path.relative_to(SERVICE_ROOT))
        for path in SERVICE_ROOT.rglob("*.py")
        if ".venv" not in path.parts and FORBIDDEN.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
