import json
import sys
from urllib.parse import urlparse

from openai import OpenAI


def validate_image_path_url(image_path_url: str) -> str:
    """Validate that the image is given as an http(s) URL."""
    url = urlparse(image_path_url)
    if url.scheme not in ("http", "https") or not url.netloc:
        raise ValueError(f"'{image_path_url}' is not an http(s) URL")
    return image_path_url


def main(image_path_url: str, openai_api_key: str, model: str = "gpt-4o-mini") -> str:
    """
    Analyze an image using OpenAI Vision API.

    Args:
        image_path_url: Public http(s) URL of the image
        openai_api_key: OpenAI API key
        model: OpenAI model identifier (default: gpt-4o-mini)

    Returns:
        str: Description of the image or error message
    """
    try:
        image_data = validate_image_path_url(image_path_url)

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