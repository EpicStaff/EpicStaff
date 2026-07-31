from github import Github
from .base_client import BaseClient
from typing import List, Dict, Any


class GitHubClient(BaseClient):
    def __init__(self, token: str, owner: str, repo_name: str):
        self.gh = Github(token)
        self.repo = self.gh.get_repo(f"{owner}/{repo_name}")
        print(f"Connected to GitHub: {owner}/{repo_name}")

    async def get_open_pull_requests(self) -> List[Dict[str, Any]]:
        prs = self.repo.get_pulls(state="open")
        return [self._format_pr(pr) for pr in prs]

    async def get_pull_requests_by_numbers(
        self, pr_numbers: List[int]
    ) -> List[Dict[str, Any]]:
        """Get specific PRs by their numbers."""
        prs = []
        for num in pr_numbers:
            try:
                pr = self.repo.get_pull(num)
                prs.append(self._format_pr(pr))
            except Exception as e:
                print(f"Warning: Could not fetch PR #{num}: {e}")
        return prs

    async def get_recent_pull_requests(self) -> List[Dict[str, Any]]:
        prs = list(self.repo.get_pulls(state="open"))[:20]
        return [self._format_pr(pr) for pr in prs]

    async def get_merged_since_last_release(self) -> List[Dict[str, Any]]:
        prs = list(self.repo.get_pulls(state="closed"))[:50]
        return [self._format_pr(pr) for pr in prs if pr.merged]

    async def get_unlabeled_pull_requests(self) -> List[Dict[str, Any]]:
        prs = self.repo.get_pulls(state="open")
        return [self._format_pr(pr) for pr in prs if len(list(pr.labels)) == 0]

    async def get_diff(self, pr_id: int) -> str:
        pr = self.repo.get_pull(pr_id)
        files = pr.get_files()
        return "\n".join(file.patch or "" for file in files)

    async def get_changed_files(self, pr_id: int) -> List[str]:
        pr = self.repo.get_pull(pr_id)
        return [file.filename for file in pr.get_files()]

    async def add_review_comment(self, pr_id: int, comment: str):
        pr = self.repo.get_pull(pr_id)
        pr.create_issue_comment(comment)

    async def add_inline_comment(
        self, pr_id: int, file_path: str, line: int, comment: str
    ):
        try:
            pr = self.repo.get_pull(pr_id)
            commit = pr.get_commits().reversed[0]

            pr.create_review_comment(
                body=comment, commit=commit, path=file_path, line=line
            )
            print(f"  ✓ Added inline comment to {file_path}:{line}")
        except Exception as e:
            print(f"  ⚠ Could not add inline comment to {file_path}:{line}: {e}")
            await self.add_review_comment(pr_id, f"**{file_path}:{line}**\n{comment}")

    async def add_comment(self, pr_id: int, comment: str):
        await self.add_review_comment(pr_id, comment)

    async def add_label(self, pr_id: int, label: str):
        pr = self.repo.get_pull(pr_id)
        pr.add_to_labels(label)

    async def update_description(self, pr_id: int, description: str):
        pr = self.repo.get_pull(pr_id)
        pr.edit(body=description)

    async def create_draft_release(self, notes: str, release_type: str = "patch"):
        latest_tag = self._get_latest_release_tag()
        next_tag = self._bump_version(latest_tag, level=release_type)

        print(f"Creating release: {latest_tag} → {next_tag} ({release_type})")

        self.repo.create_git_release(
            tag=next_tag, name=f"Release {next_tag}", message=notes, draft=True
        )

    def _get_latest_release_tag(self) -> str:
        releases = list(self.repo.get_releases())
        if not releases:
            return "v0.0.0"
        return releases[0].tag_name

    def _bump_version(self, tag: str, level: str = "patch") -> str:
        import re

        match = re.match(r"v(\d+)\.(\d+)\.(\d+)", tag)
        if not match:
            return "v0.0.0"

        major, minor, patch = map(int, match.groups())

        if level == "major":
            major += 1
            minor = 0
            patch = 0
        elif level == "minor":
            minor += 1
            patch = 0
        else:
            patch += 1

        return f"v{major}.{minor}.{patch}"

    def _format_pr(self, pr):
        return {
            "id": pr.number,
            "title": pr.title,
            "description": pr.body or "",
            "labels": [label.name for label in pr.labels],
        }
