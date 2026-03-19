# CSV Search Tool
import csv
from typing import Optional


# Simple DataType replacement
class DataType:
    CSV = "csv"


# Local base tool replacement for RagTool
class BaseRagTool:
    def __init__(self):
        self.csv_files = []

    def add(self, csv_path: str, data_type=None):
        if data_type == DataType.CSV:
            self.csv_files.append(csv_path)

    def _run(
        self,
        query: str,
        similarity_threshold: Optional[float] = None,
        limit: Optional[int] = None,
    ):
        results = []
        for csv_path in self.csv_files:
            try:
                with open(csv_path, newline="", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if any(query.lower() in str(cell).lower() for cell in row):
                            results.append(row)
                            if limit and len(results) >= limit:
                                return results
            except FileNotFoundError:
                results.append(f"CSV file not found: {csv_path}")
        return results


# Tool implementation
class CSVSearchTool(BaseRagTool):
    name: str = "Search a CSV's content"
    description: str = (
        "A tool that can be used to semantic search a query from a CSV's content."
    )

    def __init__(self, csv: Optional[str] = None):
        super().__init__()
        if csv:
            self.add(csv, data_type=DataType.CSV)
            self.description = f"A tool that can be used to semantic search a query in the {csv} CSV's content."

    def run(
        self,
        search_query: str,
        csv: Optional[str] = None,
        similarity_threshold: Optional[float] = None,
        limit: Optional[int] = None,
    ):
        if csv:
            self.add(csv, data_type=DataType.CSV)
        return super()._run(
            query=search_query, similarity_threshold=similarity_threshold, limit=limit
        )


# Example test
if __name__ == "__main__":
    tool = CSVSearchTool("example.csv")
    print(tool.run("search term", limit=5))
