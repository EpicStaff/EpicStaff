import base64
from pathlib import Path
from typing import Optional
import json
import sys

from openai import OpenAI


def validate_image_path_url(image_path_url: str) -> str:
    """Validate local image path or URL."""
    if image_path_url.startswith("http"):
        return image_path_url

    path = Path(image_path_url)
    if not path.exists():
        raise ValueError(f"Image file does not exist: {image_path_url}")

    valid_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    if path.suffix.lower() not in valid_extensions:
        raise ValueError(
            f"Unsupported image format. Supported formats: {valid_extensions}"
        )

    return image_path_url


def encode_image(image_path: str) -> str:
    """Encode a local image file as base64."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def main(image_path_url: str, openai_api_key: str, model: str = "gpt-4o-mini") -> str:
    """
    Analyze an image using OpenAI Vision API.

    Args:
        image_path_url: Local path or URL to the image
        openai_api_key: OpenAI API key
        model: OpenAI model identifier (default: gpt-4o-mini)

    Returns:
        str: Description of the image or error message
    """
    try:
        validate_image_path_url(image_path_url)

        if image_path_url.startswith("http"):
            image_data = image_path_url
        else:
            base64_image = encode_image(image_path_url)
            # Detect MIME type from file extension
            ext = Path(image_path_url).suffix.lower()
            mime = "jpeg" if ext in [".jpg", ".jpeg"] else ext[1:]
            image_data = f"data:image/{mime};base64,{base64_image}"

        client = OpenAI(api_key=openai_api_key)
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

        # Correctly access message content
        return response.choices[0].message.content

    except Exception as e:
        return f"An error occurred: {str(e)}"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python main.py args.json")
        sys.exit(1)

    args_file = sys.argv[1]
    with open(args_file, "r") as f:
        args = json.load(f)

    result = main(
        image_path_url=args.get("image_path_url"),
        openai_api_key=args.get("openai_api_key"),
        model=args.get("model", "gpt-4o-mini")
    )
    print(result)