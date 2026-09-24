from abc import ABC, abstractmethod


class ITranscriptionClient(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def handle_messages(self) -> None: ...

    @abstractmethod
    async def process_message(self, message: dict) -> dict | None: ...

    @abstractmethod
    async def close(self) -> None: ...
