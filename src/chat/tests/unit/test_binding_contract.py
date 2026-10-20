import pytest
from domain.errors import ContractFailedError
from tests.factories import make_binding

ERRORS = ["End node output map must contain `reply`."]
GONE = "The flow does not exist in this organization."


def test_recording_contract_errors_pauses_and_stores_them():
    binding = make_binding(is_active=True)
    binding.record_contract(ERRORS, None)
    assert (binding.is_active, binding.contract_errors, binding.broken_reason) == (False, ERRORS, None)


def test_recording_a_broken_reason_pauses_and_stores_it():
    binding = make_binding(is_active=True)
    binding.record_contract([], GONE)
    assert (binding.is_active, binding.contract_errors, binding.broken_reason) == (False, [], GONE)


@pytest.mark.parametrize("is_active", [True, False])
def test_recording_a_clean_contract_clears_both_and_keeps_is_active(is_active):
    binding = make_binding(is_active=is_active, contract_errors=ERRORS if not is_active else [], broken_reason=GONE)
    binding.record_contract([], None)
    assert (binding.is_active, binding.contract_errors, binding.broken_reason) == (is_active, [], None)


def test_resume_with_contract_errors_raises_and_stays_paused():
    binding = make_binding(is_active=False, contract_errors=ERRORS)
    with pytest.raises(ContractFailedError) as raised:
        binding.resume()
    assert raised.value.extra["contract_errors"] == ERRORS
    assert binding.is_active is False


def test_resume_with_a_clean_contract_activates():
    binding = make_binding(is_active=False)
    binding.resume()
    assert binding.is_active is True
