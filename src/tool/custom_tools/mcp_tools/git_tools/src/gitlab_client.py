import gitlab
from .base_client import BaseClient
from typing import List, Dict, Any


class GitLabClient(BaseClient):
    def __init__(self, token: str, url: str, owner: str, repo_name: str):
        self.gl = gitlab.Gitlab(url, private_token=token)
        self.project = self.gl.projects.get(f"{owner}/{repo_name}", lazy=True)
        print(f"Connected to GitLab: {owner}/{repo_name}")

    async def get_open_pull_requests(self) -> List[Dict[str, Any]]:
        mrs = self.project.mergerequests.list(state="opened")
        return [self._format_mr(mr) for mr in mrs]

    async def get_pull_requests_by_numbers(
        self, pr_numbers: List[int]
    ) -> List[Dict[str, Any]]:
        mrs = []
        for num in pr_numbers:
            try:
                mr = self.project.mergerequests.get(num)
                mrs.append(self._format_mr(mr))
            except Exception as e:
                print(f"Warning: Could not fetch MR !{num}: {e}")
        return mrs

    async def get_recent_pull_requests(self) -> List[Dict[str, Any]]:
        mrs = self.project.mergerequests.list(state="opened", per_page=20)
        return [self._format_mr(mr) for mr in mrs]

    async def get_merged_since_last_release(self) -> List[Dict[str, Any]]:
        mrs = self.project.mergerequests.list(state="merged", per_page=50)
        return [self._format_mr(mr) for mr in mrs]

    async def get_unlabeled_pull_requests(self) -> List[Dict[str, Any]]:
        mrs = self.project.mergerequests.list(state="opened")
        return [self._format_mr(mr) for mr in mrs if not mr.labels]

    async def get_diff(self, pr_id: int) -> str:
        mr = self.project.mergerequests.get(pr_id)
        changes = mr.changes()
        return "\n".join(
            change.get("diff", "") for change in changes.get("changes", [])
        )

    async def get_changed_files(self, pr_id: int) -> List[str]:
        mr = self.project.mergerequests.get(pr_id)
        changes = mr.changes()
        return [
            change.get("new_path", change.get("old_path", ""))
            for change in changes.get("changes", [])
        ]

    async def add_review_comment(self, pr_id: int, comment: str):
        mr = self.project.mergerequests.get(pr_id)
        mr.notes.create({"body": comment})

    async def add_inline_comment(
        self, pr_id: int, file_path: str, line: int, comment: str
    ):
        try:
            mr = self.project.mergerequests.get(pr_id)

            mr.discussions.create(
                {
                    "body": comment,
                    "position": {
                        "position_type": "text",
                        "new_path": file_path,
                        "new_line": line,
                        "base_sha": mr.diff_refs["base_sha"],
                        "start_sha": mr.diff_refs["start_sha"],
                        "head_sha": mr.diff_refs["head_sha"],
                    },
                }
            )
            print(f"  ✓ Added inline comment to {file_path}:{line}")
        except Exception as e:
            print(f"  ⚠ Could not add inline comment to {file_path}:{line}: {e}")
            await self.add_review_comment(pr_id, f"**{file_path}:{line}**\n{comment}")

    async def add_comment(self, pr_id: int, comment: str):
        await self.add_review_comment(pr_id, comment)

    async def add_label(self, pr_id: int, label: str):
        mr = self.project.mergerequests.get(pr_id)
        labels = list(mr.labels) + [label]
        mr.labels = labels
        mr.save()

    async def update_description(self, pr_id: int, description: str):
        mr = self.project.mergerequests.get(pr_id)
        mr.description = description
        mr.save()

    async def create_draft_release(self, notes: str, release_type: str = "patch"):
        latest_tag = self._get_latest_release_tag()
        next_tag = self._bump_version(latest_tag, level=release_type)
        
        print(f"Creating draft release: {latest_tag} → {next_tag} ({release_type})")
        
        milestone = self.project.milestones.create({
            'title': f'next_release_draft_{next_tag}',
            'description': f"""# Release Notes: {next_tag}

        {notes}

        ---

        **Release Type:** {release_type.upper()}  
        **Previous Version:** {latest_tag}

        ### Publishing Instructions

        1. **Review and edit** release notes above
        2. **When ready to publish:**
        - Go to Repository → Tags → New tag
        - Tag name: `{next_tag}`
        - Manually copy the release notes from this milestone description
        - Paste into "Release notes" field
        - Select this milestone: `next_release_draft_{next_tag}`
        3. **After publishing:** Close this milestone
        """,
                'state': 'active'
        })
        
        return {
            "platform": "gitlab",
            "type": "milestone",
            "next_tag": next_tag,
            "previous_tag": latest_tag,
            "release_type": release_type,
            "milestone_id": milestone.id,
            "milestone_url": milestone.web_url,
            "milestone_title": milestone.title,
            "message": f"Draft release created as milestone: {next_tag}"
        }

    def _get_latest_release_tag(self) -> str:
        import re
        
        def is_valid_version(tag_name: str) -> bool:
            exclude_patterns = ["draft", "temp", "test"]
            tag_lower = tag_name.lower()
            
            for pattern in exclude_patterns:
                if pattern in tag_lower:
                    return False
            
            return bool(re.match(r"^v?\d+\.\d+\.\d+$", tag_name))
        
        try:
            releases = self.project.releases.list(per_page=1)
            if releases and is_valid_version(releases[0].tag_name):
                return releases[0].tag_name
        except Exception as e:
            print(f"Warning: Could not fetch releases: {e}")
        
        try:
            tags = self.project.tags.list(per_page=100, order_by='updated', sort='desc')
            for tag in tags:
                if is_valid_version(tag.name):
                    return tag.name
        except Exception as e:
            print(f"Warning: Could not fetch tags: {e}")
        
        return "v0.0.0"

    def _bump_version(self, tag: str, level: str = "patch") -> str:
        import re
        
        tag_clean = tag.lstrip('v')
        match = re.match(r"(\d+)\.(\d+)\.(\d+)", tag_clean)
        
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

    def _format_mr(self, mr):
        return {
            "id": mr.iid,
            "title": mr.title,
            "description": mr.description or "",
            "labels": mr.labels,
        }
