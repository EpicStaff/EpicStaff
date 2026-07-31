from typing import Any, Dict, List, Literal, Optional, Union
from fastmcp import FastMCP

from src import ClientFactory

mcp = FastMCP("GitTools")


@mcp.tool
async def get_open_pull_requests(
    client_type: Literal["github", "gitlab"],
    token: str,
    owner: str,
    repo_name: str,
    url: str = "https://gitlab.com",
) -> List[Dict[str, Any]]:
    """Get all opened pull requests"""
    client = ClientFactory.create_client(
        client_type=client_type, token=token, owner=owner, repo_name=repo_name, url=url
    )
    return await client.get_open_pull_requests()


@mcp.tool
async def get_pull_requests_by_numbers(
    client_type: Literal["github", "gitlab"],
    token: str,
    owner: str,
    repo_name: str,
    pr_numbers: List[int],
    url: str = "https://gitlab.com",
) -> List[Dict[str, Any]]:
    """Get specific PRs by their numbers."""
    client = ClientFactory.create_client(
        client_type=client_type, token=token, owner=owner, repo_name=repo_name, url=url
    )
    return await client.get_pull_requests_by_numbers(pr_numbers)


@mcp.tool
async def get_recent_pull_requests(
    client_type: Literal["github", "gitlab"],
    token: str,
    owner: str,
    repo_name: str,
    url: str = "https://gitlab.com",
) -> List[Dict[str, Any]]:
    """Get recent pull requests."""
    client = ClientFactory.create_client(
        client_type=client_type, token=token, owner=owner, repo_name=repo_name, url=url
    )
    return await client.get_recent_pull_requests()


@mcp.tool
async def get_merged_since_last_release(
    client_type: Literal["github", "gitlab"],
    token: str,
    owner: str,
    repo_name: str,
    url: str = "https://gitlab.com",
) -> List[Dict[str, Any]]:
    "Get merged pull requests since last release"
    client = ClientFactory.create_client(
        client_type=client_type, token=token, owner=owner, repo_name=repo_name, url=url
    )
    return await client.get_merged_since_last_release()


@mcp.tool
async def get_unlabeled_pull_requests(
    client_type: Literal["github", "gitlab"],
    token: str,
    owner: str,
    repo_name: str,
    url: str = "https://gitlab.com",
) -> List[Dict[str, Any]]:
    """Get unlabeled pull requests"""
    client = ClientFactory.create_client(
        client_type=client_type, token=token, owner=owner, repo_name=repo_name, url=url
    )
    return await client.get_unlabeled_pull_requests()


@mcp.tool
async def get_diff(
    client_type: Literal["github", "gitlab"],
    token: str,
    owner: str,
    repo_name: str,
    pr_id: Union[int, str],
    url: str = "https://gitlab.com",
) -> str:
    """Get diff by pull request"""
    pr_id_int = int(pr_id) if isinstance(pr_id, str) else pr_id
    client = ClientFactory.create_client(
        client_type=client_type, token=token, owner=owner, repo_name=repo_name, url=url
    )
    return await client.get_diff(pr_id_int)


@mcp.tool
async def get_changed_files(
    client_type: Literal["github", "gitlab"],
    token: str,
    owner: str,
    repo_name: str,
    pr_id: Union[int, str],
    url: str = "https://gitlab.com",
) -> List[str]:
    """Get changed files by pull request id"""
    pr_id_int = int(pr_id) if isinstance(pr_id, str) else pr_id
    client = ClientFactory.create_client(
        client_type=client_type, token=token, owner=owner, repo_name=repo_name, url=url
    )
    return await client.get_changed_files(pr_id_int)


@mcp.tool
async def add_review_comment(
    client_type: Literal["github", "gitlab"],
    token: str,
    owner: str,
    repo_name: str,
    pr_id: Union[int, str],
    comment: str,
    url: str = "https://gitlab.com",
):
    """Add comment to pull request"""
    pr_id_int = int(pr_id) if isinstance(pr_id, str) else pr_id
    client = ClientFactory.create_client(
        client_type=client_type, token=token, owner=owner, repo_name=repo_name, url=url
    )
    return await client.add_review_comment(pr_id_int, comment)


@mcp.tool
async def add_inline_comment(
    client_type: Literal["github", "gitlab"],
    token: str,
    owner: str,
    repo_name: str,
    pr_id: Union[int, str],
    file_path: str,
    line: int,
    comment: str,
    url: str = "https://gitlab.com",
):
    """Add inline comment to pull request in specific file and line"""
    pr_id_int = int(pr_id) if isinstance(pr_id, str) else pr_id
    client = ClientFactory.create_client(
        client_type=client_type, token=token, owner=owner, repo_name=repo_name, url=url
    )
    return await client.add_inline_comment(
        pr_id=pr_id_int, file_path=file_path, line=line, comment=comment
    )


@mcp.tool
async def add_comment(
    client_type: Literal["github", "gitlab"],
    token: str,
    owner: str,
    repo_name: str,
    pr_id: Union[int, str],
    comment: str,
    url: str = "https://gitlab.com",
):
    """Add comment to pull request"""
    pr_id_int = int(pr_id) if isinstance(pr_id, str) else pr_id
    client = ClientFactory.create_client(
        client_type=client_type, token=token, owner=owner, repo_name=repo_name, url=url
    )
    return await client.add_comment(pr_id=pr_id_int, comment=comment)


@mcp.tool
async def add_label(
    client_type: Literal["github", "gitlab"],
    token: str,
    owner: str,
    repo_name: str,
    pr_id: Union[int, str],
    label: str,
    url: str = "https://gitlab.com",
):
    """Add label to pull request"""
    pr_id_int = int(pr_id) if isinstance(pr_id, str) else pr_id
    client = ClientFactory.create_client(
        client_type=client_type, token=token, owner=owner, repo_name=repo_name, url=url
    )
    return await client.add_label(pr_id=pr_id_int, label=label)


@mcp.tool
async def update_description(
    client_type: Literal["github", "gitlab"],
    token: str,
    owner: str,
    repo_name: str,
    pr_id: Union[int, str],
    description: str,
    url: str = "https://gitlab.com",
):
    """Update pull request description"""
    pr_id_int = int(pr_id) if isinstance(pr_id, str) else pr_id
    client = ClientFactory.create_client(
        client_type=client_type, token=token, owner=owner, repo_name=repo_name, url=url
    )
    return await client.update_description(pr_id=pr_id_int, description=description)


@mcp.tool
async def create_draft_release(
    client_type: Literal["github", "gitlab"],
    token: str,
    owner: str,
    repo_name: str,
    notes: str,
    release_type: Literal["major", "minor", "patch"] = "patch",
    url: str = "https://gitlab.com",
):
    """Create draft release with notes"""
    client = ClientFactory.create_client(
        client_type=client_type, token=token, owner=owner, repo_name=repo_name, url=url
    )
    return await client.create_draft_release(notes=notes, release_type=release_type)


@mcp.tool
async def get_pull_requests(
    client_type: Literal["github", "gitlab"],
    token: str,
    owner: str,
    repo_name: str,
    pr_numbers: Optional[List[int]] = None,
    url: str = "https://gitlab.com",
) -> List[Dict[str, Any]]:
    """Get pull reuqests."""
    client = ClientFactory.create_client(
        client_type=client_type, token=token, owner=owner, repo_name=repo_name, url=url
    )
    return await client.get_pull_requests(pr_numbers=pr_numbers)


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
