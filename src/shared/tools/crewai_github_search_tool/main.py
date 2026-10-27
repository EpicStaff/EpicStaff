# Remote GitHub Search Tool
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
    Search a public Git repo, given by its http(s) URL, for a query.

    Args:
        search_query (str): Query string to search.
        repo_path_or_url (str): http(s) URL of the repo, e.g. a GitHub URL.
        file_types (List[str], optional): List of file extensions to include.

    Returns:
        str: Matching file paths and snippet lines.
    """
    url = urlparse(repo_path_or_url)
    if url.scheme not in ("http", "https") or not url.netloc:
        return f"Error: '{repo_path_or_url}' is not an http(s) URL"

    temp_dir = tempfile.mkdtemp()
    try:
        print(f"Cloning remote repo {repo_path_or_url} into {temp_dir} ...")
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", repo_path_or_url, temp_dir],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            return f"Error cloning repo: {e.stderr.decode()}"
        except OSError as e:
            return f"Error cloning repo: could not run git ({e})"

        matches = []
        for root, _, files in os.walk(temp_dir):
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
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    if not matches:
        return "No matches found."
    return "\n".join(matches)