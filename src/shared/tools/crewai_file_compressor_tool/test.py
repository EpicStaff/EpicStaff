from main import main

if __name__ == "__main__":
    input_path = input("Enter file or directory to compress: ").strip()
    format = input("Enter compression format (zip, tar, tar.gz, tar.bz2, tar.xz): ").strip() or "zip"
    output_path = input("Enter output file path (leave empty for default): ").strip() or None
    overwrite_input = input("Overwrite if exists? (y/N): ").strip().lower()
    overwrite = overwrite_input == "y"

    result = main(input_path, output_path, overwrite, format)
    print(result)