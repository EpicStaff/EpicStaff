import json
from main import main

if __name__ == "__main__":
    # Ask user for required parameters
    url = input("Enter URL to scrape: ").strip()
    api_key = input("Enter Scrapfly API Key: ").strip()
    scrape_format = input("Enter format (raw, markdown, text) [markdown]: ").strip() or "markdown"
    ignore_failures = input("Ignore failures? (y/n) [n]: ").strip().lower() == "y"

    result = main(
        url=url,
        api_key=api_key,
        scrape_format=scrape_format,
        ignore_scrape_failures=ignore_failures
    )

    print("Scraped content:\n")
    print(result)