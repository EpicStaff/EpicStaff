# Vision Tool (OpenAI Vision)
#
# `openai_api_key` is NOT a function parameter: args_schema.json declares it
# with "input_type": "user_input", so it is set in the tool configuration and
# the sandbox injects it as a module-level global -- the agent never sees it.
from urllib.parse import urlparse

from openai import OpenAI
from epicstaff_common import require_setting, safe_error_message


def validate_image_path_url(image_path_url: str) -> str:
    """Validate that the image is given as an http(s) URL."""
    url = urlparse(image_path_url)
    if url.scheme not in ("http", "https") or not url.netloc:
        raise ValueError(f"'{image_path_url}' is not an http(s) URL")
    return image_path_url


def main(image_path_url: str, model: str = "gpt-4o-mini", **kwargs) -> str:
    """
    Analyze an image using OpenAI Vision API.

    Args:
        image_path_url: Public http(s) URL of the image
        model: OpenAI model identifier (default: gpt-4o-mini)

    Returns:
        str: Description of the image or error message
    """
    try:
        image_data = validate_image_path_url(image_path_url)
    except ValueError as error:
        return f"An error occurred: {error}"

    try:
        client = OpenAI(api_key=require_setting(globals(), "openai_api_key"))
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What's in this image?"},
                        {"type": "image_url", "image_url": {"url": image_data}},
                    ],
                }
            ],
        )

        return response.choices[0].message.content

    except Exception as error:
        return f"An error occurred: {safe_error_message(error)}"
