"""Import/export of the virtual environments Python code runs in.

The environment lives in the sandbox service; this side owns only the binding that
says which organization may reach it. So a strategy entry is a pair: the upstream
venv and the local binding, created together and addressed from the file by the
binding's pk like every other entity.

Reuse matters here beyond saving a build: `PythonCodeTool` is matched for reuse on
the venv its code points at, so an import that re-created an identical environment
would also re-create every tool running in it.
"""

from django.db.models import Q
from packaging.utils import canonicalize_name
from proxies.sandbox.models import SandboxVenvBinding
from proxies.sandbox.services import VenvService
from rbac.authorship import resolve_author
from rest_framework.exceptions import ValidationError

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.venv import VenvImportSerializer
from tables.import_export.strategies.base import EntityImportExportStrategy

# Mirrors VenvStatus in the sandbox service; the gateway passes the value through.
FAILED_STATUS = "failed"


class VenvStrategy(EntityImportExportStrategy):
    entity_type = EntityType.VENV
    serializer_class = VenvImportSerializer

    def get_instance(self, entity_id: int) -> SandboxVenvBinding | None:
        return SandboxVenvBinding.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: SandboxVenvBinding) -> dict:
        """Name the environment rather than its binding id, which means nothing to a reader."""
        venv = VenvService().retrieve(instance)
        return {"id": instance.pk, "name": venv.get("name")}

    def extract_dependencies_from_instance(self, instance: SandboxVenvBinding) -> dict:
        return {}

    def export_entity(self, instance: SandboxVenvBinding) -> dict:
        """The environment as the file carries it.

        Raises:
            ValidationError: It installs a custom library, which no file can carry.
                Rendered as 400.
        """
        venv = VenvService().retrieve(instance)
        libs = venv.get("libs") or []
        self._assert_no_custom_libraries(venv.get("name"), libs)
        return {
            "id": instance.pk,
            "name": venv.get("name"),
            "libs": [self._export_lib(lib) for lib in libs],
        }

    def get_org_scope_q(self, org_id: int) -> Q:
        if org_id is None:
            return Q()
        return Q(org_id=org_id)

    def find_existing(
        self, data: dict, id_mapper: IDMapper, org_id: int | None = None
    ) -> SandboxVenvBinding | None:
        """Reuse an environment of this org with the same name and the same libraries.

        Without an org there is nothing to scope reuse to, so a fresh environment is
        created rather than some other tenant's being adopted. A build that failed is
        passed over: handing the flow a known-broken environment is worse than
        building another one.
        """
        if org_id is None:
            return None

        name = data.get("name")
        libraries = self._library_key(data.get("libs") or [])
        _page, pairs = VenvService().list_page(
            SandboxVenvBinding.objects.filter(self.get_org_scope_q(org_id))
        )

        for venv, binding in pairs:
            if venv.get("status") == FAILED_STATUS or venv.get("name") != name:
                continue
            if self._library_key(venv.get("libs") or []) != libraries:
                continue
            return binding
        return None

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> SandboxVenvBinding:
        """Create the environment upstream, then the binding that owns it locally.

        The upstream write is not covered by the import's transaction, so the new id
        is recorded for the caller to compensate if the import later rolls back.
        """
        serializer = self.serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        declared = serializer.validated_data

        binding, _venv = VenvService().create(
            {"name": declared["name"], "libs": [dict(lib) for lib in declared["libs"]]},
            org_id=kwargs.get("org_id"),
            created_by=resolve_author(kwargs.get("user")),
            created_venv_ids=kwargs.get("created_venv_ids"),
        )
        return binding

    @staticmethod
    def _assert_no_custom_libraries(name: str | None, libs: list[dict]) -> None:
        """Refuse to write out an environment built on a package stored here.

        A custom library is a package this installation holds itself, so it exists
        only for the organization that uploaded it. A file can carry the name but
        never the package, and on the other side that name would be resolved against
        a package index -- another package entirely, or nothing at all. Refused while
        the file format cannot carry the library with the environment.

        Raises:
            ValidationError: Some library of the environment is a custom one.
        """
        custom_names = [str(lib.get("name")) for lib in libs if lib.get("is_custom")]
        if not custom_names:
            return
        raise ValidationError(
            f"Venv '{name}' uses custom libraries ({', '.join(custom_names)}). "
            "Exporting a venv that uses custom libraries is not supported yet, "
            "because the file cannot carry the packages themselves."
        )

    @staticmethod
    def _export_lib(lib: dict) -> dict:
        """One library as the file carries it: a name and what to resolve it against.

        `version` is not carried: it holds the author's pin and the build's own
        result in one field, so a pin with no specification of its own is written
        out as a specifier instead, and a resolved version is dropped.
        """
        specification = lib.get("specification") or ""
        version = lib.get("version")
        if not specification and version:
            specification = f"=={version}"
        return {"name": lib.get("name"), "specification": specification}

    @staticmethod
    def _library_key(libs: list[dict]) -> frozenset[tuple[str, str, bool]]:
        """What makes two environments the same set of libraries, order aside.

        Names are canonicalized the way the sandbox canonicalizes them, so `Pydantic`
        and `pydantic` do not read as two different libraries and build a duplicate.

        Where the package comes from is part of what makes them the same: a stored
        library and a package index entry of that name are two different packages,
        and reusing one for the other would install something the file never asked
        for.
        """
        return frozenset(
            (
                canonicalize_name(lib.get("name") or ""),
                (lib.get("specification") or "").strip(),
                bool(lib.get("is_custom")),
            )
            for lib in libs
        )
