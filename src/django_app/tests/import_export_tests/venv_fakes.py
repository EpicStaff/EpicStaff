"""The sandbox service, as far as import/export of virtual environments can see it.

The environment itself lives in the sandbox and only its binding lives here, so the
sandbox is the external boundary these tests replace. Shared by every test that
exports or imports an environment; the `sandbox` fixture in `conftest.py` patches it in.
"""

from proxies.sandbox.models import SandboxVenvBinding

# Both the strategy and the rollback reach the sandbox through the same service.
SANDBOX_CLIENT = "proxies.sandbox.services.VenvService.client_class"


class FakeSandbox:
    """Holds the environments it was told about, hands out ids of its own, and
    records every removal so a rollback can be checked."""

    def __init__(self, venvs: dict | None = None):
        self.venvs = dict(venvs or {})
        self.removed: list[str] = []
        self._next_id = 9000

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def create(self, data: dict) -> dict:
        self._next_id += 1
        venv = {
            "id": self._next_id,
            "name": data["name"],
            "libs": data["libs"],
            "status": "declared",
        }
        self.venvs[self._next_id] = venv
        return venv

    def retrieve(self, venv_id: str) -> dict:
        return self.venvs[int(venv_id)]

    def list(self, *, ids, search=None, order=None, limit=None, offset=None) -> dict:
        wanted = {int(venv_id) for venv_id in ids}
        return {"result": [v for key, v in self.venvs.items() if key in wanted]}

    def remove(self, venv_id: str) -> None:
        self.removed.append(venv_id)


def upstream_venv(sandbox, org, *, name="scraper-venv", libs=None, status="completed", venv_id):
    """An environment the sandbox already has, bound to `org`.

    `venv_id` is the id the sandbox knows the environment under and is deliberately
    never the binding's pk: confusing the two would run code in the wrong environment.
    """
    sandbox.venvs[venv_id] = {
        "id": venv_id,
        "name": name,
        "libs": libs if libs is not None else [{"name": "httpx", "specification": ">=0.28"}],
        "status": status,
    }
    return SandboxVenvBinding.objects.create(org_id=org.id, resource_id=str(venv_id))
