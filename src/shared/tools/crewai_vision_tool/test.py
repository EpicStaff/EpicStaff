import json
from main import main

def test_vision_tool():
    # Ask user for input
    image_path_url = input("Enter local image path or URL: ").strip()
    openai_api_key = input("Enter OpenAI API key: ").strip()

    args = {
        "image_path_url": image_path_url,
        "openai_api_key": openai_api_key
    }

    # Save args to JSON for main.py usage
    with open("args.json", "w") as f:
        json.dump(args, f)

    # Call the main function
    result = main(
        image_path_url=args["image_path_url"],
        openai_api_key=args["openai_api_key"]
    )

    print("Vision Tool Output:\n", result)


if __name__ == "__main__":
    test_vision_tool()