from tables.exceptions import CustomAPIExeption


class SurfaceValidationError(CustomAPIExeption):
    status_code = 400
    default_detail = "Invalid surface data."
    default_code = "surface_invalid"
