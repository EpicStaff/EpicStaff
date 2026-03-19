import os
from main import main

def create_example_file(file_path: str):
    """Create a sample file with 20 lines for testing."""
    lines = [f"Line {i+1}\n" for i in range(20)]
    with open(file_path, "w") as f:
        f.writelines(lines)

def run_test():
    example_file = "example_file.txt"

    # Create example file
    create_example_file(example_file)
    print(f"Created example file: {example_file}\n")

    # Read full file
    content_full = main(file_path=example_file)
    print("--- Full File Content ---")
    print(content_full)

    # Read lines 5-10
    content_partial = main(file_path=example_file, start_line=5, line_count=6)
    print("\n--- Lines 5-10 ---")
    print(content_partial)

    # Clean up example file
    os.remove(example_file)
    print(f"\nDeleted example file: {example_file}")

if __name__ == "__main__":
    run_test()