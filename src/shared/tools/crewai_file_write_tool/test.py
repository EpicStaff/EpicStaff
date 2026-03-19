from main import main

if __name__ == "__main__":
    print("Testing File Writer Tool\n")

    # Ask for inputs
    filename = input("Enter filename: ").strip()
    content = input("Enter content: ").strip()
    directory = input("Enter directory (optional, default './'): ").strip() or "./"
    overwrite_input = input("Overwrite if exists? (true/false): ").strip() or "false"

    # Run main
    result = main(
        filename=filename,
        content=content,
        directory=directory,
        overwrite=overwrite_input
    )

    print("\nResult:")
    print(result)