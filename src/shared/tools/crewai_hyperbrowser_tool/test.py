import os
from main import main

if __name__ == "__main__":
    api_key = os.getenv("HYPERBROWSER_API_KEY")
    if not api_key:
        api_key = input("Enter your Hyperbrowser API key (free/limited keys supported): ").strip()

    url = input("Enter URL to scrape/crawl (example: https://example.com): ").strip()
    operation = input("Operation (scrape/crawl) [scrape]: ").strip() or "scrape"

    try:
        content = main(url=url, operation=operation, api_key=api_key)
        print("Result:\n", content[:1000])  # limit output to first 1000 chars
    except Exception as e:
        print("Error:", e)