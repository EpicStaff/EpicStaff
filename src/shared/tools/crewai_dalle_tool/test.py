import main as tool

def test_dall_e_tool():
    # Ask user for input
    prompt = input("Enter the image description: ").strip()
    # The sandbox injects tool configuration values as module globals.
    tool.api_key = input("Enter your OpenAI API key: ").strip()

    if not prompt:
        print("Image description cannot be empty.")
        return
    if not tool.api_key:
        print("API key cannot be empty.")
        return

    result = tool.main(prompt)
    print("Generated Image Result:", result)


if __name__ == "__main__":
    test_dall_e_tool()
