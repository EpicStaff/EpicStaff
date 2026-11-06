# OCR Tool (OpenAI Vision)
#
# `openai_api_key` is NOT a function parameter: args_schema.json declares it
# with "input_type": "user_input", so it is set in the tool configuration and
# the sandbox injects it as a module-level global -- the agent never sees it.
from urllib.parse import urlparse

from openai import OpenAI
from epicstaff_common import require_setting, safe_error_message


def main(image_path_url: str, **kwargs) -> str:
    """
    Perform OCR on an image using OpenAI Vision models.

    Args:
        image_path_url (str): Public http(s) URL of the image.

    Returns:
        str: Extracted raw text from the image.
    """
    url = urlparse(image_path_url)
    if url.scheme not in ("http", "https") or not url.netloc:
        return f"ERROR: '{image_path_url}' is not an http(s) URL"

    try:
        client = OpenAI(api_key=require_setting(globals(), "openai_api_key"))
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert OCR engine. Extract ALL visible text from the image. Output raw text only."
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": image_path_url}
                        }
                    ]
                }
            ],
            temperature=0
        )
    except Exception as error:
        return f"ERROR: {safe_error_message(error)}"

    return response.choices[0].message.content