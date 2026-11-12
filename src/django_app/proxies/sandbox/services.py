"""The sandbox's resources as this side of the boundary owns them: the venv or
the custom library in the sandbox service and the binding that says which
organization may reach it, created, changed and removed as one pair.

Every caller that needs the pair goes through here -- the gateway viewset, the
importer, and the data migration that moved `PythonCode.libraries` into the
sandbox -- instead of assembling it once in each of them.

Payloads going upstream are passed through untouched, the way the rest of the
gateway treats them: a field the sandbox learns about reaches it without a change
here. What this module adds is the local half -- the binding, the rules only this
database can answer, and the cleanup of an environment whose binding is gone.
"""

from collections.abc import Iterable

from django.db.models import Q, QuerySet
from loguru import logger
from packaging.utils import canonicalize_name
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    PythonNode,
    WebhookTriggerNode,
)
from tables.models.python_models import PythonCodeTool

from proxies.models import AbstractBinding
from proxies.sandbox.clients import SandboxCustomLibraryClient, SandboxVenvClient
from proxies.sandbox.errors import UnknownCustomLibraryError, VenvInUseError
from proxies.sandbox.models import SandboxCustomLibraryBinding, SandboxVenvBinding

__all__ = ["CustomLibraryService", "VenvService"]

#: How many owners a refusal names before the rest become a count.
MAX_NAMED_OWNERS = 5


def pair_with_bindings(
    page: dict, bindings_by_resource_id: dict[str, AbstractBinding]
) -> list[tuple[dict, AbstractBinding]]:
    """Take `result` off the page and pair each row with the binding that owns it.

    A row the sandbox returned without a binding among these is dropped: it belongs
    to another organization, or to no one. This is what keeps the answer inside the
    organization, so both gateways go through it rather than each filtering its own.
    """
    pairs = []
    for item in page.pop("result", None) or []:
        binding = bindings_by_resource_id.get(str(item.get("id")))
        if binding is not None:
            pairs.append((item, binding))
    return pairs


def _name_or_none(
    client: SandboxVenvClient | SandboxCustomLibraryClient, resource_id: str
) -> str | None:
    """The name the sandbox stores for an environment or library, or None when it could
    not be asked.

    Best effort: the name only labels a user-action record, which must not fail the
    change it describes for want of it.
    """
    try:
        return client.retrieve(resource_id).get("name")
    except Exception:
        logger.exception("Could not read the name of sandbox resource {}", resource_id)
        return None


class VenvService:
    """The sandbox's environments and their bindings, handled as one resource."""

    client_class = SandboxVenvClient

    # Not `list`: a method of that name shadows the builtin for every annotation in
    # this class body, and `list[int]` below would index the method.
    def list_page(
        self,
        bindings: QuerySet[SandboxVenvBinding],
        *,
        search: str | None = None,
        order: str | None = None,
        limit: str | None = None,
        offset: str | None = None,
    ) -> tuple[dict, list[tuple[dict, SandboxVenvBinding]]]:
        """One page of the environments `bindings` reaches, each paired with its binding.

        An environment the sandbox lists without a binding among these is left out: it
        belongs to another organization, or to no one.

        `search` and `order` go upstream untouched: the sandbox owns what they mean, and
        it narrows and sorts before it pages, which this side cannot do afterwards.

        Returns:
            The page without its `result`, and the pairs that would have filled it. What
            an environment looks like in an answer differs per caller, so the page comes
            back carrying only the counts and the links.
        """
        bindings_by_resource_id = {binding.resource_id: binding for binding in bindings}
        with self.client_class() as client:
            page = client.list(
                ids=list(bindings_by_resource_id),
                search=search,
                order=order,
                limit=limit,
                offset=offset,
            )

        pairs = pair_with_bindings(page, bindings_by_resource_id)
        return page, pairs

    def retrieve(self, binding: SandboxVenvBinding) -> dict:
        """The environment this binding points at, as the sandbox reports it."""
        with self.client_class() as client:
            return client.retrieve(binding.resource_id)

    def create(
        self,
        data: dict,
        *,
        org_id: int | None,
        created_by=None,
        created_venv_ids: list[int] | None = None,
    ) -> tuple[SandboxVenvBinding, dict]:
        """Create the environment upstream, then the binding that owns it locally.

        `created_venv_ids` collects the upstream ids of everything created through it,
        for a caller whose own work can still roll back: the binding goes with the
        rollback, the environment does not, and `remove_upstream()` undoes it.

        Returns:
            The new binding and the environment the sandbox stored.

        Raises:
            UnknownCustomLibraryError: Some declared stored library is not this
                organization's. Rendered as 400.
        """
        self._assert_custom_libraries_owned(data, org_id)
        with self.client_class() as client:
            venv = client.create(data)

        if created_venv_ids is not None:
            created_venv_ids.append(venv["id"])

        # TODO: bind the venv and the binding in one transaction -- if this write
        # fails the upstream venv is orphaned (compensation/atomic deferred).
        binding = SandboxVenvBinding.objects.create(
            org_id=org_id,
            created_by=created_by,
            resource_id=str(venv["id"]),
        )
        return binding, venv

    def update(self, binding: SandboxVenvBinding, data: dict) -> dict:
        """Apply a partial change to the environment this binding points at.

        Raises:
            UnknownCustomLibraryError: Some declared stored library is not this
                organization's. Rendered as 400.
        """
        self._assert_custom_libraries_owned(data, binding.org_id)
        with self.client_class() as client:
            return client.update(binding.resource_id, data)

    def delete(self, binding: SandboxVenvBinding) -> str | None:
        """Delete an environment nothing runs in any more, upstream and here.

        `PythonCode.venv` is PROTECTed, so the delete would fail regardless; the
        refusal is raised first so the caller is told what is in the way instead of
        getting an integrity error, and so the upstream environment is never removed
        before that is known.

        Returns:
            The environment's name, read just before it is removed, since nothing can
            tell it afterwards; None when the sandbox could not be asked.

        Raises:
            VenvInUseError: Some Python code still points at it. Rendered as 409.
        """
        code_ids = list(binding.python_codes.values_list("pk", flat=True))
        if code_ids:
            raise VenvInUseError(self._describe_owners(code_ids))

        with self.client_class() as client:
            name = _name_or_none(client, binding.resource_id)
            client.remove(binding.resource_id)
        binding.delete()
        return name

    def remove_upstream(self, venv_ids: Iterable[int]) -> None:
        """Delete environments a caller created upstream, after that caller rolled back.

        The rollback already took their bindings with it. Left alone, the sandbox
        would keep an environment no organization can see, use, or delete through
        the API -- only directly in its database.

        Best effort by design: the caller has already failed and must be told about
        that failure, not about a failed cleanup.
        """
        venv_ids = list(venv_ids)
        if not venv_ids:
            return
        with self.client_class() as client:
            for venv_id in venv_ids:
                try:
                    client.remove(str(venv_id))
                except Exception:
                    logger.exception(
                        "Could not remove venv {} created by work that rolled back", venv_id
                    )

    def _assert_custom_libraries_owned(self, data: dict, org_id: int | None) -> None:
        """Refuse a venv that names a stored library the organization does not have.

        A stored library is named, not pointed at by id, and the sandbox knows
        nothing about organizations: left unchecked, a venv could name another
        organization's private package and have the build install it.

        Raises:
            UnknownCustomLibraryError: Some name is not this organization's.
        """
        declared = self._declared_custom_library_names(data)
        if not declared:
            return
        unknown = declared - self._owned_custom_library_names(org_id)
        if unknown:
            raise UnknownCustomLibraryError(
                f"This organization has no custom library named {self._name_list(sorted(unknown))}."
            )

    @staticmethod
    def _declared_custom_library_names(data: dict) -> set[str]:
        """The stored libraries a payload names, under the spelling the sandbox stores.

        An entry without the marking is a package index lookup and names no stored
        library, whatever it is called.
        """
        return {
            canonicalize_name(library["name"])
            for library in data.get("libs") or []
            if isinstance(library, dict) and library.get("is_custom") and library.get("name")
        }

    @staticmethod
    def _owned_custom_library_names(org_id: int | None) -> set[str]:
        """Every stored library this organization may name. Without an org, none."""
        if org_id is None:
            return set()
        bindings = SandboxCustomLibraryBinding.objects.filter(org_id=org_id)
        _page, pairs = CustomLibraryService().list_page(bindings)
        return {canonicalize_name(library["name"]) for library, _ in pairs if library.get("name")}

    def _describe_owners(self, code_ids: list[int]) -> str:
        live, binned = self._owner_names(code_ids)
        if live:
            return (
                f"This environment is still used by {self._name_list(live)}. "
                "Move them to another environment before deleting it."
            )
        if binned:
            # Telling the caller to move these would be a dead end: a binned tool or node
            # is in no flow and in no tool list, so there is nothing to open and change.
            return (
                f"This environment is kept by {self._name_list(binned)} in the recycle bin, "
                "which could still be restored. Empty the recycle bin to release it."
            )
        # Deleting a tool or a node does not delete its PythonCode, so a row can
        # outlive everything that referenced it. Nothing in the UI points at what
        # is holding the venv, so say that instead of naming nothing.
        return (
            "This environment is still referenced by Python code that no tool or node "
            "uses any more."
        )

    @staticmethod
    def _owner_names(code_ids: list[int]) -> tuple[list[str], list[str]]:
        """Every tool and node whose code runs in the venv, live ones and binned ones apart.

        Binned ones still hold the environment: they can be restored, and they would
        need the one they were built against. They are reported apart because the caller
        cannot act on them the way it acts on a live owner.

        The flag is read in the same pass rather than queried twice per model: the live
        and the binned name are wanted together, and one query per model answers both.
        """
        owners: list[tuple[str, bool]] = [
            *PythonCodeTool.all_objects.filter(python_code_id__in=code_ids).values_list(
                "name", "active"
            ),
            *PythonNode.all_objects.filter(python_code_id__in=code_ids).values_list(
                "node_name", "active"
            ),
            *WebhookTriggerNode.all_objects.filter(python_code_id__in=code_ids).values_list(
                "node_name", "active"
            ),
            *ClassificationDecisionTableNode.all_objects.filter(
                Q(pre_python_code_id__in=code_ids) | Q(post_python_code_id__in=code_ids)
            ).values_list("node_name", "active"),
        ]
        live = {name for name, active in owners if active}
        binned = {name for name, active in owners if not active} - live
        return sorted(live), sorted(binned)

    @staticmethod
    def _name_list(names: list[str]) -> str:
        shown = ", ".join(names[:MAX_NAMED_OWNERS])
        if len(names) > MAX_NAMED_OWNERS:
            shown = f"{shown} and {len(names) - MAX_NAMED_OWNERS} more"
        return shown


class CustomLibraryService:
    """The sandbox's custom libraries and their bindings, handled as one resource.

    A library's wheels have no binding of their own, so every wheel call takes the
    library's binding: that is what says the organization may reach them at all.
    """

    client_class = SandboxCustomLibraryClient

    def list_page(
        self,
        bindings: QuerySet[SandboxCustomLibraryBinding],
        *,
        limit: str | None = None,
        offset: str | None = None,
    ) -> tuple[dict, list[tuple[dict, SandboxCustomLibraryBinding]]]:
        """One page of the libraries `bindings` reaches, each paired with its binding.

        Returns:
            The page without its `result`, and the pairs that would have filled it.
            What a library looks like in an answer differs per caller, so the page
            comes back carrying only the counts and the links.
        """
        bindings_by_resource_id = {binding.resource_id: binding for binding in bindings}
        with self.client_class() as client:
            page = client.list(
                ids=list(bindings_by_resource_id),
                limit=limit,
                offset=offset,
            )

        pairs = pair_with_bindings(page, bindings_by_resource_id)
        return page, pairs

    def retrieve(self, binding: SandboxCustomLibraryBinding) -> dict:
        """The library this binding points at, as the sandbox reports it."""
        with self.client_class() as client:
            return client.retrieve(binding.resource_id)

    def create(
        self,
        file,
        *,
        org_id: int | None,
        created_by=None,
    ) -> tuple[SandboxCustomLibraryBinding, dict]:
        """Create the library upstream from a wheel, then the binding that owns it.

        No name is ever passed: the sandbox reads it off the wheel's own filename, so
        the registered name and the distribution it serves can never come apart.

        Returns:
            The new binding and the library the sandbox stored.
        """
        with self.client_class() as client:
            library = client.create(file)

        # TODO: bind the library and the binding in one transaction -- if this write
        # fails the upstream library is orphaned (compensation/atomic deferred).
        binding = SandboxCustomLibraryBinding.objects.create(
            org_id=org_id,
            created_by=created_by,
            resource_id=str(library["id"]),
        )
        return binding, library

    def delete(self, binding: SandboxCustomLibraryBinding) -> str | None:
        """Delete a library no venv names any more, upstream and here.

        Which venvs name it is the sandbox's to answer, not this database's: it
        refuses with a 409 while one still does, and the binding is then left alone.

        Returns:
            The library's name, read just before it is removed, since nothing can
            tell it afterwards; None when the sandbox could not be asked.
        """
        with self.client_class() as client:
            name = _name_or_none(client, binding.resource_id)
            client.remove(binding.resource_id)
        binding.delete()
        return name

    def name(self, binding: SandboxCustomLibraryBinding) -> str | None:
        """The library's name as the sandbox stores it; None when it could not be asked."""
        with self.client_class() as client:
            return _name_or_none(client, binding.resource_id)

    def list_wheels(self, binding: SandboxCustomLibraryBinding) -> list[dict]:
        """Every version of this library, as the sandbox reports them."""
        with self.client_class() as client:
            return client.list_wheels(binding.resource_id)

    def retrieve_wheel(self, binding: SandboxCustomLibraryBinding, wheel_id: str) -> dict:
        """One version of this library."""
        with self.client_class() as client:
            return client.retrieve_wheel(binding.resource_id, wheel_id)

    def download_wheel(
        self, binding: SandboxCustomLibraryBinding, wheel_id: str
    ) -> tuple[bytes, str | None]:
        """The wheel's bytes and the `content-disposition` the sandbox named it with."""
        with self.client_class() as client:
            return client.download_wheel(binding.resource_id, wheel_id)

    def upload_wheel(self, binding: SandboxCustomLibraryBinding, file) -> dict:
        """Store an uploaded wheel or source archive as a new version of this library."""
        with self.client_class() as client:
            return client.upload_wheel(binding.resource_id, file)

    def remove_wheel(self, binding: SandboxCustomLibraryBinding, wheel_id: str) -> None:
        """Delete one version of this library."""
        with self.client_class() as client:
            client.remove_wheel(binding.resource_id, wheel_id)
