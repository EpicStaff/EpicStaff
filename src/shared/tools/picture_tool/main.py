# Picture Tool

from epicstaff_common import require_setting, safe_error_message
from openai import OpenAI


class PictureTool:
    def __init__(self):
        self.api_key = require_setting(globals(), "api_key")
        self.client = OpenAI(api_key=self.api_key)

    def generate_image(self, prompt, model, size, quality, n):
        try:
            response = self.client.images.generate(
                model=model,
                prompt=prompt,
                size=size,
                quality=quality,
                n=n,
            )
            urls = [img.url for img in response.data if img.url is not None]
            return urls

        except Exception as e:
            return f"Failed to generate image: {safe_error_message(e)}"


def main(prompt, model="dall-e-3", size="1024x1024", quality="standard", n=1, **kwargs):
    try:
        tool = PictureTool()
        return tool.generate_image(prompt, model, size, quality, n)
    except Exception as error:
        return f"Error executing tool: {safe_error_message(error)}"
