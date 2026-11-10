from tables.exceptions import CustomAPIExeption


class SurfaceValidationError(CustomAPIExeption):
    status_code = 400
    default_detail = "Invalid surface data."
    default_code = "surface_invalid"


class AgentWithOwnedSurfacesRequiresSurfacesCreateError(CustomAPIExeption):
    """Raised when a caller without CREATE on surfaces copies an agent that owns surfaces.

    The copy clones every surface the agent owns, and a row created as part of another
    needs the permission it would need on its own, as on agent import.
    """

    status_code = 403
    default_detail = (
        "This agent owns surfaces, and copying it clones them, so it requires the "
        "Create permission on surfaces."
    )
    default_code = "agent_with_owned_surfaces_requires_surfaces_create_permission"
