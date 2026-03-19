from main import main

def test_dall_e_tool():
    # Ask user for input
    prompt = input("Enter the image description: ").strip()
    api_key = input("Enter your OpenAI API key: ").strip()

    if not prompt:
        print("Image description cannot be empty.")
        return
    if not api_key:
        print("API key cannot be empty.")
        return

    result = main(prompt, api_key)
    print("Generated Image Result:", result)


if __name__ == "__main__":
    test_dall_e_tool()