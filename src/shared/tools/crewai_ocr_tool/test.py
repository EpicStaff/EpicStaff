import main as tool


if __name__ == "__main__":
    print("=== OCR TOOL TEST ===")

    # The sandbox injects tool configuration values as module globals.
    tool.openai_api_key = input("Enter OpenAI API Key: ").strip()
    image_path_url = input("Enter image URL: ").strip()

    if not tool.openai_api_key or not image_path_url:
        print("ERROR: Both OpenAI API Key and image URL are required.")
    else:
        result = tool.main(image_path_url=image_path_url)

        print("\n=== OCR RESULT ===")
        print(result)
