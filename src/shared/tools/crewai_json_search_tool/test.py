import json
import os
import tempfile
from main import main

def create_temp_json_file(data: dict) -> str:
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    json_path = temp_file.name
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return json_path

def test_json_search_tool():
    data = {
        "users": [
            {"id": 1, "name": "Alice", "role": "admin"},
            {"id": 2, "name": "Bob", "role": "user"},
            {"id": 3, "name": "Alice", "role": "worker"},
            {"id": 4, "name": "Charlie", "role": "user"},
            {"id": 5, "name": "Alice", "role": "user"}
        ]
    }

    json_path = create_temp_json_file(data)

    try:
        search_query = "Alice"
        results = main(json_path=json_path, search_query=search_query)

        print("\n=== JSONSearchTool Test Result ===")
        if results:
            for i, match in enumerate(results, 1):
                print(f"{i}: {match}")
        else:
            print("No matches found.")
        print("=== End Test ===\n")

        assert any(search_query.lower() in str(m).lower() for m in results), "Test failed: query not found"
        print("✅ Test passed: query found in JSON.")

    finally:
        if os.path.exists(json_path):
            os.remove(json_path)

if __name__ == "__main__":
    test_json_search_tool()