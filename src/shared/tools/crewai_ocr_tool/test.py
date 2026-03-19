from main import main


if __name__ == "__main__":
    print("=== OCR TOOL TEST ===")

    openai_api_key = input("Enter OpenAI API Key: ").strip()
    image_path_url = input("Enter image path or URL: ").strip()

    if not openai_api_key or not image_path_url:
        print("ERROR: Both OpenAI API Key and image path/URL are required.")
    else:
        result = main(
            openai_api_key=openai_api_key,
            image_path_url=image_path_url
        )

        print("\n=== OCR RESULT ===")
        print(result)