# DOCX Search Tool
from typing import List
from docx import Document

def main(docx: str, search_query: str) -> List[str]:
    """
    Search for a query inside a DOCX file.

    Args:
        docx (str): Path to the DOCX file.
        search_query (str): Query to search in the document.

    Returns:
        List[str]: List of paragraphs containing the query.
    """
    try:
        document = Document(docx)
        paragraphs = [p.text for p in document.paragraphs]
        results = [p for p in paragraphs if search_query.lower() in p.lower()]
        return results
    except Exception as e:
        return [f"Error: {str(e)}"]