from main import main

if __name__ == "__main__":
    url = input("Enter website URL to scrape: ").strip()
    result = main(url)
    print("\n--- SCRAPED CONTENT ---\n")
    print(result[:3000])  # safety limit for console