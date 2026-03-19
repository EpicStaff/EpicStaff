from typing import Optional, Type, List
from pydantic import BaseModel, Field
import json
import os


class FixedJSONSearchToolSchema(BaseModel):
    """Input for JSONSearchTool."""
    search_query: str = Field(
        ...,
        description="Mandatory search query you want to use to search the JSON's content",
    )


class JSONSearchToolSchema(FixedJSONSearchToolSchema):
    """Input for JSONSearchTool."""
    json_path: str = Field(
        ..., description="File path of a JSON file to be searched"
    )


class JSONSearchTool:
    name: str = "Search a JSON's content"
    description: str = "A tool to semantic search a query from a JSON's content."
    args_schema: Type[BaseModel] = JSONSearchToolSchema

    def __init__(self, json_path: Optional[str] = None):
        self.json_path = json_path
        if json_path is not None:
            self.description = f"Search tool for the JSON at {json_path}"

    def _load_json(self, path: str):
        if not os.path.exists(path):
            raise FileNotFoundError(f"JSON file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _search_recursive(self, obj, query: str) -> List[dict]:
        """Recursively search for query in JSON values."""
        matches = []

        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    matches.extend(self._search_recursive(v, query))
                elif query.lower() in str(v).lower():
                    matches.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                matches.extend(self._search_recursive(item, query))
        return matches

    def _run(
        self,
        search_query: str,
        json_path: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[dict]:
        path = json_path or self.json_path
        if path is None:
            raise ValueError("No JSON path provided")

        data = self._load_json(path)
        matches = self._search_recursive(data, search_query)

        if limit is not None:
            matches = matches[:limit]

        return matches


def main(
    json_path: str,
    search_query: str,
    limit: Optional[int] = None
) -> List[dict]:
    """
    Entrypoint for JSONSearchTool.

    Args:
        json_path (str): Path to JSON file to search.
        search_query (str): Query string to search in JSON content.
        limit (Optional[int]): Maximum number of results.

    Returns:
        List[dict]: List of JSON objects containing the query.
    """
    tool = JSONSearchTool(json_path=json_path)
    return tool._run(search_query=search_query, limit=limit)


if __name__ == "__main__":
    # CLI interactive test
    json_path = input("Enter JSON path: ")
    search_query = input("Enter search query: ")
    results = main(json_path=json_path, search_query=search_query)

    if results:
        print(f"Found {len(results)} match(es):")
        for i, match in enumerate(results, 1):
            print(f"{i}: {match}")
    else:
        print("No matches found.")