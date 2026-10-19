from rest_framework import serializers

URL_IN_MODEL_NAME_MESSAGE = (
    'A model name cannot contain "://". Put the endpoint URL in base_url instead.'
)


def reject_url_in_model_name(value: str) -> None:
    """Reject a provider model name carrying a URL.

    litellm routes some providers (Hugging Face among them) to a model name that starts
    with http(s):// when no base URL is set, sending the API key and headers there. No
    catalog name contains "://", so a name with one can only be an endpoint smuggled
    past the base_url field.
    """
    if "://" in value:
        raise serializers.ValidationError(URL_IN_MODEL_NAME_MESSAGE)
