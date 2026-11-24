from drf_spectacular.utils import OpenApiResponse

from tables.serializers.system_info_serializers import SystemInfoSerializer
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

SYSTEM_INFO_GET = {
    "summary": "Get build and feature information",
    "description": (
        "Build identity (version, git ref, commit sha, commit date) and the feature "
        "switches of this installation. It describes the whole install, so it is not "
        "scoped to an organization and any authenticated caller may read it. A build "
        "value is null when the image was built without CI build arguments."
    ),
    "responses": {
        200: SystemInfoSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
    },
}
