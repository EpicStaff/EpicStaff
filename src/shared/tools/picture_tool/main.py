from openai import OpenAI

class PictureTool: 
    def __init__(self): 
        self.api_key = state["variables"]["OPENAI_API_KEY"] 
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
            return [(data.url if hasattr(data, "url") else data.b64_json) for data in response.data] 
        
        except Exception as e: 
            return f"Failed to generate image: {e}" 
        
def main(prompt, model="dall-e-3", size="1792x1024", quality="standard", n=1): 
    tool = PictureTool() 
    return tool.generate_image(prompt, model, size, quality, n)


