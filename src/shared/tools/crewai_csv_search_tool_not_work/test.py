import csv
from main import CSVSearchTool

# Create a small CSV file for testing
csv_filename = "test_example.csv"
with open(csv_filename, mode="w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["Name", "Age", "City"])
    writer.writerow(["Alice", "30", "New York"])
    writer.writerow(["Bob", "25", "Los Angeles"])
    writer.writerow(["Charlie", "35", "Chicago"])
    writer.writerow(["Alice", "28", "San Francisco"])

# Initialize the tool
tool = CSVSearchTool(csv_filename)

# Search query
search_query = "Alice"

# Run search
results = tool.run(search_query, limit=5)

# Print results
print(f"Search results for '{search_query}':")
for i, row in enumerate(results, start=1):
    print(f"{i}: {row}")
