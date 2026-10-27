# OCR Tool (OpenAI Vision)
from urllib.parse import urlparse

from openai import OpenAI


def main(openai_api_key: str, image_path_url: str) -> str:
    """
    Perform OCR on an image using OpenAI Vision models.

    Args:
        openai_api_key (str): OpenAI API key.
        image_path_url (str): Public http(s) URL of the image.

    Returns:
        str: Extracted raw text from the image.
    """
    if not openai_api_key:
        return "ERROR: openai_api_key is required."

    url = urlparse(image_path_url)
    if url.scheme not in ("http", "https") or not url.netloc:
        return f"ERROR: '{image_path_url}' is not an http(s) URL"

    client = OpenAI(api_key=openai_api_key)

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

    return response.choices[0].message.content