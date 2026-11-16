import main as tool

if __name__ == "__main__":
    website_url = input("Enter website URL to read: ").strip()
    # The sandbox injects tool configuration values as module globals.
    tool.api_key = input("Enter Jina.ai API key: ").strip()

    if not website_url or not tool.api_key:
        print("Both website URL and API key are required.")
    else:
        content = tool.main(website_url)
        print("=== Jina.ai Website Content (first 1000 chars) ===")
        print(content[:1000])
