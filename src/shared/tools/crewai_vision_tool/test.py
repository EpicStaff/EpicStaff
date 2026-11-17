import main as tool

def test_vision_tool():
    # Ask user for input
    image_path_url = input("Enter image URL: ").strip()
    # The sandbox injects tool configuration values as module globals.
    tool.openai_api_key = input("Enter OpenAI API key: ").strip()

    result = tool.main(image_path_url=image_path_url)

    print("Vision Tool Output:\n", result)


if __name__ == "__main__":
    test_vision_tool()
