from abc import ABC, abstractmethod
from typing import List, Dict, Any, Literal, Optional


class BaseClient(ABC):
    @abstractmethod
    async def get_open_pull_requests(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_pull_requests_by_numbers(
        self, pr_numbers: List[int]
    ) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_recent_pull_requests(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_merged_since_last_release(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_unlabeled_pull_requests(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_diff(self, pr_id: int) -> str:
        pass

    @abstractmethod
    async def get_changed_files(self, pr_id: int) -> List[str]:
        pass

    @abstractmethod
    async def add_review_comment(self, pr_id: int, comment: str):
        pass

    @abstractmethod
    async def add_inline_comment(
        self, pr_id: int, file_path: str, line: int, comment: str
    ):
        pass

    @abstractmethod
    async def add_comment(self, pr_id: int, comment: str):
        pass

    @abstractmethod
    async def add_label(self, pr_id: int, label: str):
        pass

    @abstractmethod
    async def update_description(self, pr_id: int, description: str):
        pass

    @abstractmethod
    async def create_draft_release(
        self, notes: str, release_type: Literal["major", "minor", "patch"] = "patch"
    ):
        pass

    async def get_pull_requests(
        self, pr_numbers: Optional[List[int]] = None
    ) -> List[Dict[str, Any]]:
        if pr_numbers:
            return await self.get_pull_requests_by_numbers(pr_numbers)
        return await self.get_open_pull_requests()
