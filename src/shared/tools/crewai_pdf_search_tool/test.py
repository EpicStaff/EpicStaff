import os
from main import main
import urllib.request
import tempfile

def download_pdf(url: str) -> str:
    """Download PDF from URL to a temporary file and return path"""
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    with urllib.request.urlopen(url) as response:
        tmp_file.write(response.read())
    tmp_file.close()
    return tmp_file.name

if __name__ == "__main__":
    # Ask user for PDF input
    pdf_input = input("Enter PDF path or URL: ").strip()
    if pdf_input.lower().startswith("http://") or pdf_input.lower().startswith("https://"):
        print("Downloading PDF from URL...")
        pdf_path = download_pdf(pdf_input)
        print(f"PDF downloaded to temporary file: {pdf_path}")
    else:
        pdf_path = pdf_input

    # Ask for search query
    query = input("Enter search query: ").strip()

    # Ask for OpenAI API key
    api_key = input("Enter OpenAI API key: ").strip()

    # Ask for optional similarity threshold
    threshold = input("Enter similarity threshold (0-1, default 0.7): ").strip()
    threshold = float(threshold) if threshold else 0.7

    # Ask for optional limit
    limit = input("Enter number of results (default 5): ").strip()
    limit = int(limit) if limit else 5

    # Run semantic search
    result = main(
        query=query,
        pdf=pdf_path,
        openai_api_key=api_key,
        similarity_threshold=threshold,
        limit=limit
    )

    print("\n--- Search Results ---\n")
    print(result)