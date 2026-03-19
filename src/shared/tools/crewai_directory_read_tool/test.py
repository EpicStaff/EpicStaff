from main import main

def test_directory_read_tool():
    # Create a temporary directory with sample files for testing
    import tempfile, os

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create some files
        file_paths = [
            os.path.join(tmpdir, "file1.txt"),
            os.path.join(tmpdir, "subdir", "file2.txt")
        ]
        os.makedirs(os.path.join(tmpdir, "subdir"), exist_ok=True)
        for f in file_paths:
            with open(f, "w") as fp:
                fp.write("test")

        # Run the tool
        result = main(tmpdir)
        print(result)

if __name__ == "__main__":
    test_directory_read_tool()