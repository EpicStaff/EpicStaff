from main import main


def ask(prompt: str, required: bool = True) -> str:
    while True:
        value = input(prompt).strip()
        if value or not required:
            return value
        print("This value is required.")


if __name__ == "__main__":
    print("Scrape Element From Website Tool – Test\n")

    website_url = ask("Enter website URL: ")
    css_element = ask("Enter CSS selector to scrape: ")

    print("\nRunning tool...\n")

    try:
        result = main(
            website_url=website_url,
            css_element=css_element,
        )
        print("RESULT:\n")
        print(result)
    except Exception as e:
        print("ERROR:")
        print(e)