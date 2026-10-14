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

import pytest

AUTH_TOKEN = "12345"
URL = "https://mycompany.com/myapp.php?foo=1&bar=2"
SIGNATURE = "pA9T74XaVTq8oX3FDhv0CTa4HE4="


@pytest.mark.parametrize(
    ("url", "params", "signature"),
    [
        (URL, {"Digits": "1234"}, SIGNATURE),
        ("https://mycompany.com/myapp.php", {}, "ZEVhNTf/+0VuA9ofUWb9iscKI5Y="),
        ("https://mycompany.com/voice", {"CallerName": "José Ééé", "Digits": "ééé"}, "3uQRNEbmDLrQ+deYLdcjPAGi13w="),
        (
            "https://mycompany.com/voice?foo=bar&baz=qux",
            {"CallSid": "CA1234", "From": "+15551234567", "To": "+15557654321"},
            "4Nv5KQ+XmyGMTLHjs4OHW+zVRBY=",
        ),
        ("https://mycompany.com/voice", {"z_param": "last", "a_param": "first", "m_param": "middle"}, "ZcvS09xBY0g6YwbVV/QrGwIPqxI="),
        # Realtime's x-forwarded-host often lacks the port; Twilio accepts both forms.
        ("https://realtime.example.com/voice", {"CallSid": "CA5678"}, "q2xHGjOAQiwuZsNawxw0CVH3RVk="),
        ("https://realtime.example.com:8443/voice", {"CallSid": "CA9999"}, "63cgHAERSAg5q0Dtsr3C5kePAVA="),
    ],
    ids=["simple", "no-params", "unicode", "query-string", "unsorted-params", "no-port", "explicit-port"],
)
def test_twilios_signature_is_accepted(url, params, signature):
    assert validate_twilio_signature(url, params, signature, AUTH_TOKEN) is True


@pytest.mark.parametrize(
    ("signature", "auth_token"),
    [(SIGNATURE[:-1] + "A", AUTH_TOKEN), ("", AUTH_TOKEN), (SIGNATURE, "wrong-token")],
    ids=["tampered", "empty", "wrong-auth-token"],
)
def test_a_forged_signature_is_rejected(signature, auth_token):
    assert validate_twilio_signature(URL, {"Digits": "1234"}, signature, auth_token) is False
