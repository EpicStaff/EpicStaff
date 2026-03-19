# Local/Remote GitHub Search Tool
import os
import tempfile
import shutil
import subprocess
from typing import List, Optional
from urllib.parse import urlparse


def main(
    search_query: str,
    repo_path_or_url: str,
    file_types: Optional[List[str]] = None
) -> str:
    """
    Search a local or public GitHub repo for a query.

    Args:
        search_query (str): Query string to search.
        repo_path_or_url (str): Local path or GitHub URL of the repo.
        file_types (List[str], optional): List of file extensions to include.

    Returns:
        str: Matching file paths and snippet lines.
    """
    temp_dir = None
    search_path = repo_path_or_url

    # Determine if input is a URL
    if urlparse(repo_path_or_url).scheme in ("http", "https"):
        temp_dir = tempfile.mkdtemp()
        print(f"Cloning remote repo {repo_path_or_url} into {temp_dir} ...")
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", repo_path_or_url, temp_dir],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            search_path = temp_dir
        except subprocess.CalledProcessError as e:
            return f"Error cloning repo: {e.stderr.decode()}"

    # Perform the search
    matches = []
    if not os.path.isdir(search_path):
        return f"Error: '{search_path}' is not a valid directory."

    for root, _, files in os.walk(search_path):
        for file in files:
            if file_types and not any(file.endswith(ft) for ft in file_types):
                continue
            file_path = os.path.join(root, file)
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for i, line in enumerate(f, 1):
                        if search_query.lower() in line.lower():
                            matches.append(f"{file_path} (line {i}): {line.strip()}")
            except Exception as e:
                matches.append(f"{file_path}: Error reading file ({e})")

    # Cleanup temporary folder if cloned
    if temp_dir:
        shutil.rmtree(temp_dir)

    if not matches:
        return "No matches found."
    return "\n".join(matches)