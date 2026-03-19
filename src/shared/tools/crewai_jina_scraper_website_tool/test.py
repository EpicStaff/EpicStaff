from main import main

if __name__ == "__main__":
    website_url = input("Enter website URL to read: ").strip()
    api_key = input("Enter Jina.ai API key: ").strip()
    
    if not website_url or not api_key:
        print("Both website URL and API key are required.")
    else:
        content = main(website_url, api_key)
        print("=== Jina.ai Website Content (first 1000 chars) ===")
        print(content[:1000])