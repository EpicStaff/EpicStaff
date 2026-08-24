"""Locks in parity with ``twilio.request_validator.RequestValidator``.

These fixtures were generated once by running BOTH
``RequestValidator(token).validate(url, params, signature)`` and
``validate_twilio_signature(url, params, signature, token)`` side by side (with
the ``twilio`` package temporarily installed) and confirming identical results.
The expected base64 signatures below are the values Twilio's own validator
computed for these inputs (``RequestValidator(token).compute_signature(url,
params)``). This test does NOT import ``twilio`` at runtime -- it hard-codes
those known-good signatures so the dependency can never be reintroduced while
still guarding the algorithm against regressions.
"""

from utils.twilio_signature import validate_twilio_signature

AUTH_TOKEN = "12345"


def test_simple_params():
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    params = {"Digits": "1234"}
    signature = "pA9T74XaVTq8oX3FDhv0CTa4HE4="
    assert validate_twilio_signature(url, params, signature, AUTH_TOKEN) is True


def test_empty_params_dict():
    url = "https://mycompany.com/myapp.php"
    params = {}
    signature = "ZEVhNTf/+0VuA9ofUWb9iscKI5Y="
    assert validate_twilio_signature(url, params, signature, AUTH_TOKEN) is True


def test_unicode_param_values():
    url = "https://mycompany.com/voice"
    params = {"CallerName": "José Ééé", "Digits": "ééé"}
    signature = "3uQRNEbmDLrQ+deYLdcjPAGi13w="
    assert validate_twilio_signature(url, params, signature, AUTH_TOKEN) is True


def test_url_with_query_string():
    url = "https://mycompany.com/voice?foo=bar&baz=qux"
    params = {"CallSid": "CA1234", "From": "+15551234567", "To": "+15557654321"}
    signature = "4Nv5KQ+XmyGMTLHjs4OHW+zVRBY="
    assert validate_twilio_signature(url, params, signature, AUTH_TOKEN) is True


def test_params_needing_sort_reordering():
    url = "https://mycompany.com/voice"
    params = {"z_param": "last", "a_param": "first", "m_param": "middle"}
    signature = "ZcvS09xBY0g6YwbVV/QrGwIPqxI="
    assert validate_twilio_signature(url, params, signature, AUTH_TOKEN) is True


def test_no_port_in_host_matches_proxy_stripped_host():
    """Realtime's x-forwarded-host often lacks an explicit port; Twilio's
    validator accepts a signature computed either with or without the
    scheme's default port appended -- this locks in the "without port" match.
    """
    url = "https://realtime.example.com/voice"
    params = {"CallSid": "CA5678"}
    signature = "q2xHGjOAQiwuZsNawxw0CVH3RVk="
    assert validate_twilio_signature(url, params, signature, AUTH_TOKEN) is True


def test_explicit_port_in_host():
    url = "https://realtime.example.com:8443/voice"
    params = {"CallSid": "CA9999"}
    signature = "63cgHAERSAg5q0Dtsr3C5kePAVA="
    assert validate_twilio_signature(url, params, signature, AUTH_TOKEN) is True


def test_tampered_signature_is_rejected():
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    params = {"Digits": "1234"}
    valid_signature = "pA9T74XaVTq8oX3FDhv0CTa4HE4="
    tampered_signature = valid_signature[:-1] + (
        "A" if valid_signature[-1] != "A" else "B"
    )
    assert (
        validate_twilio_signature(url, params, tampered_signature, AUTH_TOKEN)
        is False
    )


def test_empty_signature_header_is_rejected():
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    params = {"Digits": "1234"}
    assert validate_twilio_signature(url, params, "", AUTH_TOKEN) is False


def test_wrong_auth_token_is_rejected():
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    params = {"Digits": "1234"}
    valid_signature = "pA9T74XaVTq8oX3FDhv0CTa4HE4="
    assert (
        validate_twilio_signature(url, params, valid_signature, "wrong-token")
        is False
    )
