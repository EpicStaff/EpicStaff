from typing import Literal

from .base_client import BaseClient
from .github_client import GitHubClient
from .gitlab_client import GitLabClient


class ClientFactoryException(ValueError): ...


class ClientFactory:
    @classmethod
    def create_client(
        cls,
        client_type: Literal["github", "gitlab"],
        token: str,
        owner: str,
        repo_name: str,
        url: str = None,
    ) -> BaseClient:
        match client_type:
            case "github":
                return GitHubClient(token=token, owner=owner, repo_name=repo_name)
            case "gitlab":
                gitlab_url = url or "https://gitlab.com"
                return GitLabClient(token=token, owner=owner, repo_name=repo_name, url=gitlab_url)
            case _:
                raise ClientFactoryException(f"Client type {client_type} is not supported")
