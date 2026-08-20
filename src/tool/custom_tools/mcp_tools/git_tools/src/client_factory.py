from typing import Literal

from .base_client import BaseClient
from .github_client import GitHubClient
from .gitlab_client import GitLabClient
from .url_policy import assert_url_allowed

GITHUB_API_URL = "https://api.github.com"
DEFAULT_GITLAB_URL = "https://gitlab.com"


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
                # PyGithub targets api.github.com; still gate it so an operator
                # allow-list that excludes GitHub blocks the token from leaving.
                assert_url_allowed(GITHUB_API_URL)
                return GitHubClient(token=token, owner=owner, repo_name=repo_name)
            case "gitlab":
                gitlab_url = assert_url_allowed(url or DEFAULT_GITLAB_URL)
                return GitLabClient(
                    token=token, owner=owner, repo_name=repo_name, url=gitlab_url
                )
            case _:
                raise ClientFactoryException(
                    f"Client type {client_type} is not supported"
                )
