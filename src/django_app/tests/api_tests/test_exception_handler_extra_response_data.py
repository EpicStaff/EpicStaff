from utils.exception_handler import custom_exception_handler
from utils.exceptions import CustomAPIExeption


class _ConflictWithExtraData(CustomAPIExeption):
    status_code = 409
    default_detail = "Something blocks this."
    default_code = "something_blocked"

    def __init__(self, extra_response_data):
        super().__init__()
        self.extra_response_data = extra_response_data


def test_extra_response_data_is_added_next_to_the_envelope():
    response = custom_exception_handler(
        _ConflictWithExtraData({"blocker": {"code": "why", "message": "Because."}}), {}
    )

    assert response.status_code == 409
    assert response.data == {
        "status_code": 409,
        "code": "something_blocked",
        "message": "Something blocks this.",
        "blocker": {"code": "why", "message": "Because."},
    }


def test_envelope_keys_win_over_colliding_extra_keys():
    response = custom_exception_handler(
        _ConflictWithExtraData(
            {"code": "overridden", "status_code": 200, "message": "overridden", "extra": 1}
        ),
        {},
    )

    assert response.data == {
        "status_code": 409,
        "code": "something_blocked",
        "message": "Something blocks this.",
        "extra": 1,
    }


def test_exception_without_extra_data_keeps_the_plain_envelope():
    response = custom_exception_handler(CustomAPIExeption("Plain."), {})

    assert CustomAPIExeption.extra_response_data is None
    assert set(response.data) == {"status_code", "code", "message"}
