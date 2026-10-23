from foundation.schemas import ErrorDetailSchema
from foundation.utils.litestar.error_handler import create_response


def test_create_response_sends_the_given_headers():
    response = create_response(
        503,
        [ErrorDetailSchema(code="overloaded", detail="No free capacity.")],
        headers={"Retry-After": "5"},
    )

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
