# OCR Tool (OpenAI Vision)
import base64
from openai import OpenAI


def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def main(openai_api_key: str, image_path_url: str) -> str:
    """
    Perform OCR on an image using OpenAI Vision models.

    Args:
        openai_api_key (str): OpenAI API key.
        image_path_url (str): Local image path or public image URL.

    Returns:
        str: Extracted raw text from the image.
    """
    if not openai_api_key:
        return "ERROR: openai_api_key is required."

    client = OpenAI(api_key=openai_api_key)

    if image_path_url.startswith("http://") or image_path_url.startswith("https://"):
        image_data = image_path_url
    else:
        base64_image = _encode_image(image_path_url)
        image_data = f"data:image/jpeg;base64,{base64_image}"

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
                        "image_url": {"url": image_data}
                    }
                ]
            }
        ],
        temperature=0
    )

    return response.choices[0].message.content