import os
import tempfile
from main import main

def create_sample_files(base_dir):
    files = {
        "file1.txt": "This is an example file with some test content.",
        "file2.txt": "Another file that contains different words and test data.",
        "file3.txt": "The quick brown fox jumps over the lazy dog.",
    }

    for filename, content in files.items():
        file_path = os.path.join(base_dir, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

def run_test():
    with tempfile.TemporaryDirectory() as temp_dir:
        create_sample_files(temp_dir)
        test_queries = ["example", "test", "fox", "over", "on", "missing"]

        for query in test_queries:
            print(f"\n--- Searching for: '{query}' ---")
            result = main(search_query=query, directory=temp_dir, limit=3)
            print(result)

if __name__ == "__main__":
    run_test()