from __future__ import annotations

from django.db import transaction
from rbac.access.resolver import PermissionResolver
from rbac.authorship import record_last_edits, resolve_author
from rbac.models.enums import Permission, ResourceType
from tables.import_export.utils import clean_base_name
from tables.models.base_models import copied_field_values
from tables.models.realtime_models import RealtimeAgentDefinition
from tables.services.copy_services.base_copy_service import BaseCopyService
from tables.services.copy_services.helpers import name_lock_key, next_copy_name

from agents.exceptions import AgentWithOwnedSurfacesRequiresSurfacesCreateError
from agents.models.agent_models import AgentDefaultSurface, AgentDefinition
from agents.models.surface_models import Surface
from agents.services.surface_service import SurfaceService

# Room kept after a cut base name for a " #N" copy suffix, N up to 9999.
_COPY_SUFFIX_RESERVE = len(" #9999")


class AgentDefinitionCopyService(BaseCopyService):
    """Copy an agent with its settings, default surfaces and realtime settings.

    Shared surfaces are re-linked; every live surface the agent owns is cloned for
    the copy, content included, and a default-surface row pointing at an owned
    surface points at its clone. Tools, LLM configs, the group and the realtime
    provider config are re-linked, never cloned, so no code or secret is copied.
    """

    def __init__(self, resolver: PermissionResolver | None = None):
        self._resolver = resolver or PermissionResolver()

    @transaction.atomic
    def copy(
        self,
        agent: AgentDefinition,
        name: str | None = None,
        org_id: int | None = None,
        user=None,
    ) -> AgentDefinition:
        """Create the copy in the agent's own organization and return it.

        Names follow the copy rule: the agent gets `name` (or the source's name)
        and each cloned surface its source's name, numbered " #N" when taken. A
        base name too long to take a suffix is cut first (see `_fitting_base_name`).
        The realtime settings are copied unchanged, wake word included, so the
        source and the copy answer to the same wake word until one is edited.

        Args:
            org_id: The caller's active organization, for the `BaseCopyService`
                contract. The copy stays in the agent's organization: LLM configs,
                the group, shared surfaces and the realtime config are re-linked by
                id, so they must stay in the org they belong to.

        Raises:
            AgentWithOwnedSurfacesRequiresSurfacesCreateError: The agent owns surfaces
                and `user` lacks CREATE on surfaces in the agent's org. Raised before
                anything is written, from the same surface list the copy clones.
            IntegrityError: A plain create or rename, which takes no copy-name lock,
                took a picked name in the meantime; the copy endpoint turns it into
                a "please retry" 400.
        """
        if org_id is not None and org_id != agent.org_id:
            raise ValueError(f"An agent of org {agent.org_id} cannot be copied into org {org_id}.")
        org_id = agent.org_id
        owned_surfaces = list(Surface.objects.filter(owner_agent=agent).order_by("pk"))
        if owned_surfaces:
            self._assert_may_clone_surfaces(user, org_id)
        default_rows = list(AgentDefaultSurface.objects.filter(agent_definition=agent))

        # The endpoint validates `name`, but CopyActionMixin passes it on untrimmed.
        requested_name = name.strip() if name else ""
        agent_name, surface_names = self._pick_names(
            agent_base_name=requested_name or agent.name,
            owned_surfaces=owned_surfaces,
            org_id=org_id,
        )
        new_agent = AgentDefinition.objects.create(
            name=agent_name,
            org_id=org_id,
            created_by=resolve_author(user),
            description=agent.description,
            instruction_list=agent.instruction_list,
            metadata=agent.metadata,
            llm_config_id=agent.llm_config_id,
            fcm_llm_config_id=agent.fcm_llm_config_id,
            # A fallback needs a primary: deleting the primary config leaves the
            # fallback behind, and the copy must not inherit that broken pair.
            fallback_llm_config_id=(
                agent.fallback_llm_config_id if agent.llm_config_id is not None else None
            ),
            max_iter=agent.max_iter,
            max_rpm=agent.max_rpm,
            max_execution_time=agent.max_execution_time,
            cache=agent.cache,
            max_retry_limit=agent.max_retry_limit,
            default_temperature=agent.default_temperature,
            max_tool_calls=agent.max_tool_calls,
            tool_timeout=agent.tool_timeout,
            max_consecutive_failures=agent.max_consecutive_failures,
            schema_max_retries=agent.schema_max_retries,
            group_id=agent.group_id,
        )

        clones_by_source_id = {
            surface.pk: SurfaceService.clone_surface(
                surface, name=surface_names[surface.pk], owner_agent=new_agent, user=user
            )
            for surface in owned_surfaces
        }
        AgentDefaultSurface.objects.bulk_create(
            [
                AgentDefaultSurface(
                    agent_definition=new_agent,
                    surface_id=(
                        clones_by_source_id[row.surface_id].pk
                        if row.surface_id in clones_by_source_id
                        else row.surface_id
                    ),
                    place=row.place,
                )
                for row in default_rows
            ]
        )
        self._copy_realtime(agent, new_agent)

        record_last_edits([new_agent, *clones_by_source_id.values()], user)
        return new_agent

    def _assert_may_clone_surfaces(self, user, org_id: int) -> None:
        # A row created as part of another needs the permission it would need on
        # its own, as on agent import.
        effective_permissions = self._resolver.resolve(user=user, org_id=org_id)
        if not effective_permissions.can(ResourceType.SURFACES, Permission.CREATE):
            raise AgentWithOwnedSurfacesRequiresSurfacesCreateError()

    @staticmethod
    def _pick_names(
        *, agent_base_name: str, owned_surfaces: list[Surface], org_id: int
    ) -> tuple[str, dict[int, str]]:
        """Return the agent's copy name and {source surface id: clone name}.

        Each `next_copy_name` call takes the advisory lock of its (org, name family),
        and agent and surface names share that key space. Taking them in lock-key
        order, as every restore does, keeps two concurrent copies from deadlocking.
        """
        agent_base_name = _fitting_base_name(AgentDefinition, agent_base_name)
        # (lock key, source surface id or None for the agent, base name). The key is
        # computed from the very string next_copy_name gets, so it is the lock it takes.
        requests = [
            (name_lock_key(org_id, clean_base_name(agent_base_name)), None, agent_base_name)
        ]
        for surface in owned_surfaces:
            surface_base_name = _fitting_base_name(Surface, surface.name)
            requests.append(
                (
                    name_lock_key(org_id, clean_base_name(surface_base_name)),
                    surface.pk,
                    surface_base_name,
                )
            )
        requests.sort(key=lambda request: (request[0], request[1] is not None, request[1] or 0))

        agent_name = ""
        surface_names: dict[int, str] = {}
        for _, surface_id, base_name in requests:
            if surface_id is None:
                agent_name = next_copy_name(AgentDefinition, org_id=org_id, base_name=base_name)
            else:
                # The clones aren't inserted yet, so names picked for earlier clones
                # of this same copy must count as taken.
                surface_names[surface_id] = next_copy_name(
                    Surface,
                    org_id=org_id,
                    base_name=base_name,
                    extra_taken_names=surface_names.values(),
                )
        return agent_name, surface_names

    @staticmethod
    def _copy_realtime(agent: AgentDefinition, new_agent: AgentDefinition) -> None:
        # Not `agent.realtime_agent`: a reverse one-to-one reads through the base
        # manager, which also returns a binned row.
        source_realtime = RealtimeAgentDefinition.objects.filter(agent_definition=agent).first()
        if source_realtime is None:
            return
        RealtimeAgentDefinition.objects.create(
            agent_definition=new_agent,
            **copied_field_values(source_realtime, exclude={"agent_definition"}),
        )


def _fitting_base_name(model, base_name: str) -> str:
    """Return `base_name`, or its name family cut short enough to take a " #N" suffix.

    next_copy_name numbers a taken name as "<family> #N", which overflows the name
    column when the family is close to max_length. The cut name is a family of its
    own: its lock key, the names counted as taken and the numbered result all come
    from the cut string, so every copy of an over-long name lands in that one family.
    A long name is cut even when it is free, as whether it is free is only known under
    the family's lock.
    """
    max_length = model._meta.get_field("name").max_length
    family = clean_base_name(base_name)
    if len(family) + _COPY_SUFFIX_RESERVE <= max_length:
        return base_name
    # rstrip: a cut ending in a space would be kept verbatim when the cut name is free.
    return family[: max_length - _COPY_SUFFIX_RESERVE].rstrip()
