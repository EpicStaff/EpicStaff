from tables.exceptions import CustomAPIExeption


class SurfaceValidationError(CustomAPIExeption):
    status_code = 400
    default_detail = "Invalid surface data."
    default_code = "surface_invalid"


class AgentDefinitionConflictError(CustomAPIExeption):
    status_code = 409
    default_detail = "An agent with this name already exists in the organization."
    default_code = "agent_definition_conflict"
