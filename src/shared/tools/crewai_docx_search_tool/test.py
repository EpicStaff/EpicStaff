from main import main

if __name__ == "__main__":
    # Simple test: adjust path and query to match your DOCX
    docx_path = "sample.docx"
    query = "dolor"

    results = main(docx=docx_path, search_query=query)
    if results:
        print("Found paragraphs:")
        for para in results:
            print("-", para)
    else:
        print("No matches found.")