"""Code that declares secrets: whether a source holds it, and who may copy or restore it.

Copying a flow or a tool, restoring or creating a flow from a version, and restoring a
recycle-bin item that brings secret-declaring code back or live all give the caller
code that reads those secrets, which needs secrets:USE (`SecretCodeAccess`, shared as
`secret_code_access`). `SecretCodeInspector` answers whether, and which, secrets a
source's code declares. Asked before anything is written, so a refusal leaves nothing
behind. A Telegram trigger's bot token is not a code declaration.
"""

from functools import reduce
from operator import or_

from django.db.models import Model, Q
from tables.exceptions import CodeWithSecretsRequiresSecretsUsePermissionError
from tables.models import Secret, WebhookTrigger
from tables.models.base_models import without_internal_rows
from tables.models.graph_models import WebhookTriggerNode
from tables.services.secrets.linked_ids import linked_ids
from tables.services.secrets.python_code_sites import (
    GRAPH_PYTHON_CODE_SITES,
    PYTHON_CODE_SITES,
)
from tables.services.secrets.secret_use_service import (
    SecretActor,
    principal_of,
    secret_use_service,
)


class SecretCodeInspector:
    """The secrets declared by a source's code, binned ones included: they stay linked until purged."""

    @staticmethod
    def declared_in_graph(graph) -> frozenset[int]:
        """Return the pks of the secrets any live node of `graph` declares. One query."""
        declared_by_a_site = reduce(
            or_,
            (
                Q(
                    python_codes__in=site.model.objects.filter(graph=graph).values(
                        f"{site.code_field}_id"
                    )
                )
                for site in GRAPH_PYTHON_CODE_SITES
            ),
        )
        rows = without_internal_rows(Secret.all_objects.filter(declared_by_a_site))
        return frozenset(rows.values_list("pk", flat=True))

    @staticmethod
    def snapshot_declares_any(snapshot: dict) -> bool:
        """Return whether a version snapshot's code declares any secret, by name. No query.

        Whether the names resolve today does not matter: a secret purged or binned now
        can be recreated or restored later, and the restored code reads it again. A
        snapshot saved before declarations were recorded declares none. A Telegram
        trigger's bot token is not a code declaration and does not count.
        """
        recorded = (snapshot.get("secret_declarations") or {}).get("nodes") or {}
        return any(
            names
            for names_by_code_field in recorded.values()
            for names in names_by_code_field.values()
        )

    @staticmethod
    def declared_in_restore(root: Model) -> frozenset[int]:
        """Return the pks of the secrets declared by code that restoring the binned `root` brings back or live.

        Two ways, as for trigger nodes (`TriggerNodeInspector.restore_brings_back_any`):
        a row of any Python-code site binned in the root's batch comes back with it (a
        flow's own nodes, a tool itself), and a webhook trigger reconnects the live
        webhook trigger nodes that kept their link to it. A binned secret counts: it
        stays linked until purged and is readable again once restored. One query.
        """
        code_ids_by_site = []
        batch = root.soft_delete_batch
        # A root binned before batches existed can't be restored (NotInRecycleBinError),
        # and filtering on a null batch would match every such row.
        if batch is not None:
            code_ids_by_site += [
                site.model.all_objects.filter(soft_delete_batch=batch, active=False).values(
                    f"{site.code_field}_id"
                )
                for site in PYTHON_CODE_SITES
            ]
        if isinstance(root, WebhookTrigger):
            code_ids_by_site.append(
                WebhookTriggerNode.objects.filter(webhook_trigger=root).values("python_code_id")
            )
        if not code_ids_by_site:
            return frozenset()
        declared_by_a_site = reduce(
            or_, (Q(python_codes__in=code_ids) for code_ids in code_ids_by_site)
        )
        rows = without_internal_rows(Secret.all_objects.filter(declared_by_a_site))
        return frozenset(rows.values_list("pk", flat=True))


_NOT_REFERENCEABLE = (
    "This credential can reference only secrets it created, so it cannot copy or restore "
    "code that reads any other secret."
)


class SecretCodeAccess:
    """Who may copy or restore code that declares secrets: the secrets:USE gates around it.

    Copying a flow or a tool, restoring a flow version or creating a flow from one, and
    restoring a recycle-bin item all give the caller code they can edit and run, which
    reads the secrets it declares. Every one of them asks here, so they refuse alike.
    The resolver decides; superadmin passes through it, never through a check here.
    """

    def assert_may_recreate(self, actor: SecretActor | None, secrets=None) -> None:
        """Assert `actor` may copy or restore code that declares secrets.

        Call it only once the source is known to declare a secret, before writing.

        Args:
            secrets: The declared secrets, in any form `linked_ids` takes. A pinned-org
                principal (a plugin's service account) must be able to reference every
                one. None when the caller limits them itself: a version restore drops
                and warns about each secret the principal may not reference.

        Raises:
            CodeWithSecretsRequiresSecretsUsePermissionError (403): `actor` lacks USE on
                secrets, or is a pinned-org principal that may not reference one of
                `secrets` (with a message saying so).
        """
        if not secret_use_service.may_use(actor):
            raise CodeWithSecretsRequiresSecretsUsePermissionError()
        principal = principal_of(actor)
        if (
            secrets is not None
            and principal is not None
            and not principal.may_reference_secrets(linked_ids(secrets))
        ):
            raise CodeWithSecretsRequiresSecretsUsePermissionError(detail=_NOT_REFERENCEABLE)

    def assert_user_may_recreate(self, user, org_id: int, secrets=None) -> None:
        """Resolve `user` in `org_id`, then apply `assert_may_recreate`."""
        self.assert_may_recreate(SecretActor.for_user(user, org_id), secrets)

    def assert_user_may_restore(self, user, org_id: int, root: Model) -> None:
        """Assert `user` may restore the recycle-bin `root` of `org_id`.

        Call it on the binned row, before restoring it, after the trigger-node check. A
        restore that brings no secret-declaring code back or live
        (`SecretCodeInspector.declared_in_restore`) resolves nothing and always passes.

        Raises:
            CodeWithSecretsRequiresSecretsUsePermissionError (403): as `assert_may_recreate`.
        """
        declared = SecretCodeInspector.declared_in_restore(root)
        if declared:
            self.assert_user_may_recreate(user, org_id, declared)


secret_code_access = SecretCodeAccess()
