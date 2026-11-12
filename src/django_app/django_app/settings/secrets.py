from django.core.exceptions import ImproperlyConfigured

from django_app.settings import env

_MIN_KEY_LENGTH = 12

# Master key the stored secret values are encrypted with; only django_app holds it.
SECRETS_ENCRYPTION_KEY = env.secret("SECRETS_ENCRYPTION_KEY")

if len(SECRETS_ENCRYPTION_KEY) < _MIN_KEY_LENGTH:
    raise ImproperlyConfigured(
        f"SECRETS_ENCRYPTION_KEY must be at least {_MIN_KEY_LENGTH} characters "
        "long. Generate a strong value with `python scripts/envtool.py`."
    )

# Replaced master keys, kept for decryption only; `none` lists no key.
SECRETS_ENCRYPTION_PREVIOUS_KEYS = tuple(
    key for key in env.list("SECRETS_ENCRYPTION_PREVIOUS_KEYS") or [] if key
)

# Key the outbound secret values are sealed with; every consuming service holds it too.
SECRETS_TRANSPORT_KEY = env.secret("SECRETS_TRANSPORT_KEY")

if len(SECRETS_TRANSPORT_KEY) < _MIN_KEY_LENGTH:
    raise ImproperlyConfigured(
        f"SECRETS_TRANSPORT_KEY must be at least {_MIN_KEY_LENGTH} characters "
        "long. Generate a strong value with `python scripts/envtool.py`."
    )

# Replaced transport keys, kept for decryption only; `none` lists no key.
SECRETS_TRANSPORT_PREVIOUS_KEYS = tuple(
    key for key in env.list("SECRETS_TRANSPORT_PREVIOUS_KEYS") or [] if key
)

# HKDF info the transport key is derived with: a wire contract with every consuming service.
# Read from the environment, which compose shares with all of them; django_app is the producer.
SECRETS_TRANSPORT_HKDF_INFO = env.str("SECRETS_TRANSPORT_HKDF_INFO")
