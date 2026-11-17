from foundation.cryptographer import FernetRotatedCryptographer

# Stands in for the transport cryptographer crew builds in main.py; tests seal values with it
# the way django_app does before a session reaches crew.
TEST_SECRETS_CRYPTOGRAPHER = FernetRotatedCryptographer(
    "test-transport-key", hkdf_info=b"epicstaff.secrets.transport.test"
)
